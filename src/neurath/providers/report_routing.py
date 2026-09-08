"""Bind provider report replies without impersonating a native executor.

Only owned worker observations and existing native registration can establish a
route. Late migration also proves that the observed worker generation is closed.
Neither path starts/resumes a process or modifies native identity records.
"""

import hashlib
import json
import os
import sqlite3
from pathlib import Path

from neurath.memory.store import canonical, control_root
from neurath.providers.contracts import Session


def schema(db):
    db.execute("""CREATE TABLE IF NOT EXISTS provider_executor_observations (
        run_id TEXT NOT NULL, generation INTEGER NOT NULL, created TEXT NOT NULL,
        PRIMARY KEY(run_id,generation))""")
    db.execute("""CREATE TABLE IF NOT EXISTS provider_executor_routes (
        run_id TEXT NOT NULL, generation INTEGER NOT NULL, recipient TEXT NOT NULL,
        identity_digest TEXT NOT NULL, PRIMARY KEY(run_id,generation))""")


def _native_executor(store, created, request, db):
    from neurath.runtime.engine import activate
    activate()
    from scripts.agent_harness.session_kernel import SessionId, SessionKernel, SessionLocator
    from neurath.hosts.identity import snapshot

    if not isinstance(created, dict):
        return None
    try:
        session = Session(**created)
        transport = {"codex": "codex-app-server", "claude-code": "claude-agent-sdk"}.get(session.provider)
        target = Path(session.worktree).resolve()
        if (session.transport != transport or session.provider != request.get("provider", "codex")
                or target != Path(request["worktree"]).resolve() or control_root(target) != store.root):
            return None
        recipient = session.provider + ":" + session.native_session
        registered = store._agent(db, recipient)
        if (not registered["is_root"] or registered["host"] != session.provider
                or registered["session"] != session.native_session
                or Path(registered["worktree"]).resolve() != target):
            return None
        state = SessionKernel(SessionLocator.from_worktree(target)).inspect(SessionId(session.native_session))
        root_actor = state.actors.get(state.session.root_actor_id)
        if (state.session.runtime.value != session.provider or root_actor is None
                or str(root_actor.id) != registered["actor"] or root_actor.parent_actor_id is not None):
            return None
        native = snapshot(target, session.native_session)
        if native.get("host") != session.provider or not native.get("start_source") or not native.get("transcript"):
            return None
        identity = [session.provider, session.transport, session.native_session, str(target), str(root_actor.id)]
        return recipient, hashlib.sha256(canonical(identity).encode()).hexdigest()
    except (OSError, ValueError, RuntimeError, KeyError, TypeError):
        return None


def observe_created(store, lease, created, db):
    """Record only the owned worker native-created callback, before registration is assumed."""
    lease.assert_current(db)
    schema(db)
    session = Session(**created)
    row = db.execute("SELECT request FROM provider_jobs WHERE id=?", (lease.run_id,)).fetchone()
    request = json.loads(row["request"])
    if (session.provider != request.get("provider", "codex")
            or Path(session.worktree).resolve() != Path(request["worktree"]).resolve()
            or session.transport != {"codex": "codex-app-server", "claude-code": "claude-agent-sdk"}.get(session.provider)):
        raise ValueError("owned native creation differs from the provider request")
    value = canonical(created)
    previous = db.execute("SELECT created FROM provider_executor_observations WHERE run_id=? AND generation=?",
                          (lease.run_id, lease.generation)).fetchone()
    if previous is not None and previous["created"] != value:
        raise ValueError("native creation observation changed within the worker generation")
    db.execute("INSERT OR IGNORE INTO provider_executor_observations VALUES(?,?,?)",
               (lease.run_id, lease.generation, value))


def bind_executor(store, row, result, lease, db):
    """Current worker lease plus observed Session/registration establishes one immutable route."""
    if lease is None:
        return None
    lease.assert_current(db)
    schema(db)
    request = json.loads(row["request"])
    observation = db.execute("SELECT created FROM provider_executor_observations WHERE run_id=? AND generation=?",
                             (row["id"], lease.generation)).fetchone()
    if observation is None:
        return None  # Prestart cancellation cannot inherit the prior native executor.
    created = json.loads(observation["created"])
    if any(result.get("created", {}).get(field) != created.get(field)
           for field in ("provider", "transport", "native_session", "worktree")):
        raise ValueError("provider result differs from its owned native creation")
    observed = _native_executor(store, created, request, db)
    if observed is None or observed[0] == row["owner"]:
        return None
    recipient, digest = observed
    old = db.execute("SELECT recipient,identity_digest FROM provider_executor_routes WHERE run_id=? AND generation=?",
                     (row["id"], lease.generation)).fetchone()
    if old is not None and tuple(old) != (recipient, digest):
        raise ValueError("provider executor route changed within the owned generation")
    db.execute("INSERT OR IGNORE INTO provider_executor_routes VALUES(?,?,?,?)",
               (row["id"], lease.generation, recipient, digest))
    return recipient


def _legacy_candidate(store, actor, message_id, db):
    report = store._message(db, message_id)
    if report["recipient"] != actor or report["sender"] != actor:
        raise ValueError("provider report reply route requires its addressed supervisor")
    task = db.execute("""SELECT t.* FROM task_events e JOIN task_links t ON t.id=e.task
        WHERE e.message=? AND t.issuer=? AND t.executor=?
        AND t.transport IN ('provider-supervisor','provider-recovery')""", (message_id, actor, actor)).fetchone()
    if task is None:
        raise ValueError("provider report reply route unavailable: not an owned provider report")
    candidates = []
    for row in db.execute("""SELECT j.id,j.owner,j.request,r.generation,r.result
        FROM provider_jobs j JOIN provider_job_results r ON r.run_id=j.id
        WHERE j.owner=? AND r.generation>0""", (actor,)):
        key = "provider:" + row["id"] + (":recovery:" + str(row["generation"]) if row["generation"] > 1 else "")
        if hashlib.sha256(canonical([actor, key]).encode()).hexdigest() == task["id"]:
            candidates.append(dict(row))
    if len(candidates) != 1:
        raise ValueError("provider report reply route unavailable: exact worker result missing")
    return candidates[0]


def restore_report_route(store, actor, message_id):
    """Attach missing routing metadata to an old immutable report after proven worker exit."""
    from neurath.providers.job_recovery import JobRecovery

    try:
        with store.connection() as db:
            existing = db.execute("SELECT recipient FROM message_reply_routes WHERE message=?", (message_id,)).fetchone()
            if existing is not None:
                return existing["recipient"]
            candidate = _legacy_candidate(store, actor, message_id, db)
        recovery = JobRecovery(store)
        descriptor = recovery._lock(candidate["id"])
        try:
            with store.connection() as db:
                current = _legacy_candidate(store, actor, message_id, db)
                if current != candidate:
                    raise ValueError("provider report reply route unavailable: result changed")
                lease = db.execute("SELECT * FROM provider_worker_leases WHERE run_id=?", (candidate["id"],)).fetchone()
                if (lease is None or lease["generation"] != candidate["generation"]
                        or lease["state"] not in {"active", "finished"} or not lease["token"]):
                    raise ValueError("provider report reply route unavailable: worker generation changed")
                result = json.loads(candidate["result"])
                created = result.get("created", {})
                closure = result.get("closure", {})
                source = {"codex-app-server": "owned-app-server-close", "claude-agent-sdk": "owned-sdk-disconnect"}.get(created.get("transport"))
                if (result.get("worker_generation") != candidate["generation"]
                        or closure.get("connection_closed") is not True
                        or closure.get("native_process_exited") is not True
                        or closure.get("native_session") != created.get("native_session")
                        or closure.get("transport") != created.get("transport")
                        or source is None or closure.get("source") != source):
                    raise ValueError("provider report reply route unavailable: native closure unverified")
                observed = _native_executor(store, created, json.loads(candidate["request"]), db)
                if observed is None or observed[0] == actor:
                    raise ValueError("provider report reply route unavailable: native registration unverified")
                recipient, digest = observed
                schema(db)
                previous = db.execute("SELECT recipient,identity_digest FROM provider_executor_routes WHERE run_id=? AND generation=?",
                    (candidate["id"], candidate["generation"])).fetchone()
                if previous is not None and tuple(previous) != observed:
                    raise ValueError("provider report reply route unavailable: conflicting executor binding")
                db.execute("INSERT OR IGNORE INTO provider_executor_routes VALUES(?,?,?,?)", (candidate["id"], candidate["generation"], recipient, digest))
                store._bind_reply_route(db, message_id, recipient)
                return recipient
        finally:
            os.close(descriptor)
    except (OSError, RuntimeError, KeyError, TypeError, sqlite3.Error) as error:
        raise ValueError("provider report reply route unavailable: " + type(error).__name__) from error

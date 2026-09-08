"""Detached, owner-scoped session supervision with durable message outcomes.

Only start() is exposed through an authenticated execution-policy gate. The
private worker consumes that accepted request once; it never assumes the issuer's
native session identity. Cancellation uses a private socket, never a stored PID.
"""

import argparse
import hashlib
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from contextlib import nullcontext
from pathlib import Path
from subprocess import Popen

from neurath.agents.lifecycle import TERMINAL, TaskLifecycle
from neurath.agents.runner import child_environment
from neurath.agents.store import MessageStore, bounded
from neurath.memory.store import canonical, clean
from neurath.providers.execution import run as execute_session
from neurath.providers.report_routing import bind_executor, observe_created


def _store(root):
    store = MessageStore(root)
    with store.connection() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS provider_jobs (
            id TEXT PRIMARY KEY, owner TEXT NOT NULL, request TEXT NOT NULL,
            status TEXT NOT NULL, result TEXT, control TEXT NOT NULL,
            cancel_requested INTEGER NOT NULL DEFAULT 0, updated REAL NOT NULL)""")
    return store


def validate_target(root, fields):
    from neurath.providers.execution import _target

    provider, mode = fields.get("provider", "codex"), fields.get("mode", "read-only")
    if provider == "claude-code":
        if mode != "native" or fields.get("permission_mode") not in {"plan", "dontAsk", "default", "acceptEdits", "bypassPermissions", "auto"}:
            raise ValueError("Claude requires its explicit native permission mode")
        mode = "read-only" if fields["permission_mode"] == "plan" else "workspace-write"
    elif provider != "codex":
        raise ValueError("unsupported provider")
    return _target(root, fields["worktree"], mode)


def _launch(*args, **kwargs):
    process = Popen(*args, **kwargs)
    # Reap this exact child asynchronously; the long-lived MCP must not retain
    # zombies. Waiting here happens only in a daemon thread, never in start().
    threading.Thread(target=process.wait, daemon=True).start()


def _owned(db, owner, run_id):
    row = db.execute("SELECT * FROM provider_jobs WHERE id=?", (run_id,)).fetchone()
    if row is None or row["owner"] != owner:
        raise ValueError("provider job requires its owner")
    return row


def status(root, identity, run_id):
    with _store(root).connection() as db:
        row = _owned(db, identity.address, run_id)
        return {"run_id": run_id, "status": row["status"],
                "cancel_requested": bool(row["cancel_requested"]),
                "result": json.loads(row["result"]) if row["result"] else None}


def start(root, identity, fields, *, key=""):
    """Accept once; reconcile an unconsumed initial request under current authority."""
    key = key or uuid.uuid4().hex
    bounded(key, "provider request key")
    store = _store(root)
    tasks = TaskLifecycle(store)
    run_id = hashlib.sha256(canonical([identity.address, key]).encode()).hexdigest()
    request = canonical(fields)
    replayed = False
    with store.connection() as db:
        store._agent(db, identity.address)
        previous = db.execute("SELECT * FROM provider_jobs WHERE id=?", (run_id,)).fetchone()
        if previous:
            if previous["owner"] != identity.address or previous["request"] != request:
                raise ValueError("provider request key changed request")
            replayed = True
            result = json.loads(previous["result"]) if previous["result"] else {}
            if previous["status"] != "accepted" or "created" in result:
                return {"run_id": run_id, "status": previous["status"], "implementation_dispatched": False,
                        "delivery": "durable-events", "replayed": True}
            control = previous["control"]
        else:
            validate_target(root, fields)
            control = tempfile.mkdtemp(prefix="neurath-job-", dir="/tmp")
            db.execute("INSERT INTO provider_jobs(id,owner,request,status,control,updated) VALUES(?,?,?,?,?,?)",
                       (run_id, identity.address, request, "accepted", control, time.time()))
            tasks.bind(identity.address, identity.address, key="provider:" + run_id,
                       transport="provider-supervisor", _db=db)
    from neurath.providers.job_recovery import JobRecovery, RecoveryUnavailable
    recovery = JobRecovery(store)

    def current():
        return {**status(root, identity, run_id), "implementation_dispatched": False,
                "delivery": "durable-events", "replayed": True,
                "reconciliation": "worker-owned-or-advanced"}

    def finish(diagnostic):
        def terminal(db, lease):
            cancelled = db.execute("SELECT cancel_requested FROM provider_jobs WHERE id=?", (run_id,)).fetchone()[0]
            return _finish(store, run_id, {"run_id": run_id, "status": "cancelled" if cancelled else "failed",
                "implementation_dispatched": False, "diagnostic": clean(diagnostic),
                "retryable": False, "worker_generation": lease.generation}, lease, _db=db, _tasks=tasks)
        try:
            return recovery.finish_initial(identity.address, run_id, terminal)
        except RecoveryUnavailable:
            return current()

    try:
        state = recovery.initial_state(identity.address, run_id)
    except RecoveryUnavailable:
        return current()
    if state != "launch":
        return finish("initial admission cancelled" if state == "cancel" else
                      "initial worker consumed its lease but exited before observable start")
    try:
        if replayed:
            validate_target(root, fields)
        # Concurrent launchers may race here. Only the worker OS lease and CAS
        # consume this initial request; successful Popen is not native execution.
        with (Path(control) / "worker.log").open("ab") as log:
            _launch([sys.executable, "-I", "-m", "neurath.providers.jobs", "--root",
                              str(Path(root).resolve()), "--run-id", run_id],
                             cwd=fields["worktree"], env=child_environment(),
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=log, start_new_session=True)
    except (OSError, ValueError) as error:
        return finish(str(error))
    return {"run_id": run_id, "status": "accepted", "implementation_dispatched": False,
            "delivery": "durable-events", "replayed": replayed,
            "reconciliation": "initial-worker-launched"}


def cancel(root, identity, run_id):
    from neurath.providers.job_recovery import JobRecovery, RecoveryUnavailable
    store = _store(root)
    recovery = JobRecovery(store)
    tasks = TaskLifecycle(store)
    with store.connection() as db:
        row = _owned(db, identity.address, run_id)
        lease = db.execute("SELECT generation,state FROM provider_worker_leases WHERE run_id=?", (run_id,)).fetchone()
        generation = lease["generation"] if lease and lease["state"] == "accepted" and lease["generation"] > 1 else None
        pending = row["status"] not in TERMINAL or generation is not None
        if pending:
            db.execute("UPDATE provider_jobs SET cancel_requested=1 WHERE id=?", (run_id,))
        control = row["control"]
    if generation is not None:
        try:
            recovery.cancel_unstarted(identity.address, run_id, generation,
                lambda db, lease: _finish(store, run_id, {"status": "cancelled", "run_id": run_id,
                    "worker_generation": generation, "implementation_dispatched": False}, lease,
                    _db=db, _tasks=tasks))
            return {"run_id": run_id, "cancel_requested": True}
        except RecoveryUnavailable:
            pass  # The worker may have claimed first; its durable flag remains set.
    if pending:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as connection:
            try:
                connection.sendto(b"cancel", str(Path(control) / "control.sock"))
            except (FileNotFoundError, ConnectionRefusedError):
                pass  # A not-yet-started worker consumes the persisted cancellation once.
    return {"run_id": run_id, "cancel_requested": pending}


def _finish(store, run_id, result, lease=None, *, _db=None, _tasks=None):
    if result["status"] not in TERMINAL:
        result = {**result, "provider_status": result["status"], "status": "failed"}
    from neurath.providers.job_recovery import archive_result
    tasks = _tasks if _tasks is not None else TaskLifecycle(store)
    with store.connection() if _db is None else nullcontext(_db) as db:
        if lease is not None:
            lease.assert_current(db)
        row = db.execute("SELECT * FROM provider_jobs WHERE id=?", (run_id,)).fetchone()
        owner = row["owner"]
        if row["status"] in TERMINAL and lease is None:
            return json.loads(row["result"])
        previous = json.loads(row["result"]) if row["result"] else {}
        if lease is not None and lease.generation > 1:
            previous = {k: v for k, v in previous.items() if k in {"created", "closure", "model_plan", "policy_inheritance"}}
        result = {**previous, **result}
        reply_recipient = bind_executor(store, row, result, lease, db)
        result["reply_route"] = {"status": "bound" if reply_recipient else "unavailable", "recipient": reply_recipient}
        db.execute("UPDATE provider_jobs SET status=?,result=?,updated=? WHERE id=?",
                   (result["status"], canonical(result), time.time(), run_id))
        task_key = "provider:" + run_id + (":recovery:" + str(lease.generation) if lease is not None and lease.generation > 1 else "")
        task_id = hashlib.sha256(canonical([owner, task_key]).encode()).hexdigest()
        if lease is not None and lease.generation > 1:
            tasks.bind(owner, owner, key=task_key, transport="provider-recovery", _db=db)
        archive_result(db, run_id, lease.generation if lease is not None else 0, result)
        tasks.emit(owner, task_id, result["status"], key="terminal",
                   detail=canonical(result).encode()[:15000].decode("utf-8", errors="ignore"),
                   reply_recipient=reply_recipient, _db=db)
        if lease is not None:
            db.execute("UPDATE provider_worker_leases SET state='finished' WHERE run_id=? AND generation=? AND token=?",
                       (run_id, lease.generation, lease.token))
    return result


class Cancelled(Exception):
    pass


def recover(root, identity, run_id, *, key):
    """The task dispatcher checks current issuer authority before this operation."""
    from neurath.providers.job_recovery import ClosedTransportEvidence, JobRecovery, RecoveryBlocked
    store = _store(root)
    with store.connection() as db:
        row = _owned(db, identity.address, run_id)
        result = json.loads(row["result"]) if row["result"] else {}
        closure = result.get("closure")
        control = Path(row["control"])
    if not closure or not result.get("worker_generation"):
        raise RecoveryBlocked("owned native process/connection closure is unverified")
    evidence = ClosedTransportEvidence(generation=result["worker_generation"], issuer_active=True, **closure)
    tasks = TaskLifecycle(store)
    def admitted(db, admission):
        tasks.bind(identity.address, identity.address,
                   key="provider:" + run_id + ":recovery:" + str(admission["generation"]),
                   transport="provider-recovery", _db=db)
    outcome = JobRecovery(store).recover(identity.address, run_id, key, evidence, on_admit=admitted)
    generation = outcome["admission"]["generation"]
    # Reconcile an accepted-but-not-launched generation. The OS lease and CAS
    # allow exactly one worker to consume it even when launch responses are lost.
    with store.connection() as db:
        state = db.execute("SELECT state FROM provider_worker_leases WHERE run_id=? AND generation=?",
                           (run_id, generation)).fetchone()
    if state and state["state"] == "accepted":
        with (control / "worker.log").open("ab") as log:
            _launch([sys.executable, "-I", "-m", "neurath.providers.jobs", "--root", str(Path(root).resolve()),
                     "--run-id", run_id, "--recovery-generation", str(generation)],
                    cwd=outcome["admission"]["session"]["worktree"], env=child_environment(),
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=log, start_new_session=True)
    return {"run_id": run_id, "status": "recovery-accepted", "generation": generation,
            "replayed": outcome["replayed"], "implementation_dispatched": False}


def worker(root, run_id, generation=0):
    store = _store(root)
    from neurath.providers.job_recovery import JobRecovery
    with store.connection() as db:
        row = db.execute("SELECT owner,cancel_requested FROM provider_jobs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise ValueError("provider job missing")
    with JobRecovery(store).claim_worker(row["owner"], run_id, generation=generation, allow_cancelled=True) as lease:
        with store.connection() as db:
            cancelled = db.execute("SELECT cancel_requested FROM provider_jobs WHERE id=?", (run_id,)).fetchone()[0]
        if cancelled:
            return _finish(store, run_id, {"status": "cancelled", "run_id": run_id,
                "worker_generation": lease.generation, "implementation_dispatched": False}, lease)
        return _worker(root, run_id, store, lease, recovery=generation > 0)


def _worker(root, run_id, store, lease, *, recovery=False):
    with store.connection() as db:
        lease.assert_current(db)
        row = db.execute("SELECT * FROM provider_jobs WHERE id=?", (run_id,)).fetchone()
        if row is None or not recovery and row["status"] != "accepted":
            raise ValueError("provider job already consumed or missing")
        fields, owner, control = json.loads(row["request"]), row["owner"], Path(row["control"])
        if recovery:
            from neurath.providers.contracts import Session
            prior = json.loads(row["result"])
            fields["restored_session"] = Session(**prior["created"])
            fields["model"] = prior["created"]["actual_model"]
            fields["model_plan"] = prior.get("model_plan", fields.get("model_plan"))
            fields["assignment"] = ("Restore your Neurath collaboration inbox in this existing session. "
                "Read pending messages with collaboration_inbox and collaboration_message, acknowledge their bodies, "
                "and act on authorized follow-ups. Use stable message IDs to recognize duplicates. "
                "This recovery does not repeat the original assignment or undo a completed result.")
        db.execute("UPDATE provider_jobs SET status='starting',updated=? WHERE id=?", (time.time(), run_id))
    tasks = TaskLifecycle(store)
    task_key = "provider:" + run_id + (":recovery:" + str(lease.generation) if recovery else "")
    task_id = hashlib.sha256(canonical([owner, task_key]).encode()).hexdigest()
    if recovery:
        tasks.bind(owner, owner, key=task_key, transport="provider-recovery")
    previous = signal.getsignal(signal.SIGUSR1)
    finishing = False
    def interrupted(signum, frame):
        if not finishing:
            raise Cancelled("explicit owner cancellation")
    signal.signal(signal.SIGUSR1, interrupted)
    endpoint = control / "control.sock"
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    receiver = None
    sequence = 0
    def observed(state, detail):
        nonlocal sequence
        sequence += 1
        with store.connection() as db:
            lease.assert_current(db)
            if state == "native-created":
                observe_created(store, lease, detail["created"], db)
                previous = db.execute("SELECT result FROM provider_jobs WHERE id=?", (run_id,)).fetchone()[0]
                partial = json.loads(previous) if previous else {}
                partial.update(detail)
                partial["worker_generation"] = lease.generation
                db.execute("UPDATE provider_jobs SET result=?,updated=? WHERE id=?", (canonical(partial), time.time(), run_id))
                return
            current = db.execute("SELECT * FROM provider_jobs WHERE id=?", (run_id,)).fetchone()
            partial = json.loads(current["result"]) if current["result"] else {}
            reply_recipient = bind_executor(store, current, partial, lease, db)
            tasks.emit(owner, task_id, state, key=f"event:{sequence}",
                       detail=canonical(detail).encode()[:15000].decode("utf-8", errors="ignore"),
                       reply_recipient=reply_recipient, _db=db)
            db.execute("UPDATE provider_jobs SET status=?,updated=? WHERE id=?", (state, time.time(), run_id))
    try:
        connection.bind(str(endpoint))
        endpoint.chmod(0o600)
        def receive_control():
            try:
                if connection.recv(32) == b"cancel":
                    os.kill(os.getpid(), signal.SIGUSR1)
            except OSError:
                pass
        with store.connection() as db:
            if db.execute("SELECT cancel_requested FROM provider_jobs WHERE id=?", (run_id,)).fetchone()[0]:
                raise Cancelled("cancelled before native session creation")
        receiver = threading.Thread(target=receive_control, daemon=True)
        receiver.start()
        observed("starting", {"run_id": run_id})
        # Ordinary sessions have no execution deadline. RPC handshakes remain bounded.
        execution_fields = {key: value for key, value in fields.items() if key not in {
            "model_request", "plan_id", "plan_revision", "assignment_revision"}}
        if "model_plan" in execution_fields:
            execution_fields.update(model_owner=owner, run_id=run_id)
        result = execute_session(root, **execution_fields, timeout=None, event_callback=observed)
    except Cancelled as error:
        result = {"status": "cancelled", "diagnostic": str(error)}
    except Exception as error:  # noqa: BLE001 - persist unexpected worker failures before exit
        result = {"status": "failed", "diagnostic": clean(f"{type(error).__name__}: {error}")}
    finally:
        # A late datagram must not interrupt the terminal transaction or reach
        # the default signal handler between transport cleanup and result commit.
        finishing = True
        if receiver is not None:
            # Wake the blocking reader once so it cannot signal after we restore
            # the previous handler. This is an event, not a periodic status scan.
            with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as wake:
                wake.sendto(b"stop", str(endpoint))
            receiver.join()
        connection.close()
        endpoint.unlink(missing_ok=True)
    try:
        return _finish(store, run_id, {**result, "run_id": run_id, "worker_generation": lease.generation}, lease)
    finally:
        signal.signal(signal.SIGUSR1, previous)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--recovery-generation", type=int, default=0)
    args = parser.parse_args()
    worker(Path(args.root), args.run_id, args.recovery_generation)

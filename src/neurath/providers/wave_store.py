"""Provider-wave schema, owner lookup and persisted read projections.

Callers supply the active transaction so task validation, reservations, results
and after-commit notifications remain atomic in the application service.
"""

import hashlib
import json

from neurath.agents.lifecycle import TERMINAL
from neurath.agents.store import bounded
from neurath.providers.job_store import open_store
from neurath.providers.wave_policy import digest, entry_state, request_scope
from neurath.serialization import canonical


def open_wave_store(root):
    store = open_store(root)
    with store.connection() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS provider_waves (
            id TEXT PRIMARY KEY, public_id TEXT NOT NULL, owner TEXT NOT NULL, actor TEXT NOT NULL,
            session TEXT NOT NULL, task_id TEXT NOT NULL, request TEXT NOT NULL,
            cancel_requested INTEGER NOT NULL DEFAULT 0, blocked_reason TEXT NOT NULL DEFAULT '')""")
        db.execute("""CREATE TABLE IF NOT EXISTS provider_wave_entries (
            wave_id TEXT NOT NULL, entry_id TEXT NOT NULL, ordinal INTEGER NOT NULL,
            run_id TEXT UNIQUE, state TEXT NOT NULL DEFAULT 'queued',
            consumption TEXT, attempt INTEGER NOT NULL DEFAULT 0, request_override TEXT, PRIMARY KEY(wave_id,entry_id))""")
        db.execute("""CREATE TABLE IF NOT EXISTS provider_wave_outbox (
            run_id TEXT PRIMARY KEY, wave_id TEXT NOT NULL, diagnostic TEXT NOT NULL DEFAULT '')""")
        db.execute("""CREATE TABLE IF NOT EXISTS provider_wave_attempts (
            wave_id TEXT NOT NULL, entry_id TEXT NOT NULL, attempt INTEGER NOT NULL,
            run_id TEXT UNIQUE NOT NULL, record TEXT NOT NULL, PRIMARY KEY(wave_id,entry_id,attempt))""")
        db.execute("""CREATE TABLE IF NOT EXISTS provider_wave_retries (
            owner TEXT NOT NULL, key TEXT NOT NULL, wave_id TEXT NOT NULL, entry_id TEXT NOT NULL,
            request TEXT NOT NULL, request_digest TEXT NOT NULL, PRIMARY KEY(owner,key))""")
        db.execute("""CREATE TABLE IF NOT EXISTS provider_wave_operations (
            owner TEXT NOT NULL, key TEXT NOT NULL, request TEXT NOT NULL,
            PRIMARY KEY(owner,key))""")
        db.execute("""CREATE TABLE IF NOT EXISTS provider_wave_supersessions (
            old_wave_id TEXT PRIMARY KEY, new_wave_id TEXT NOT NULL,
            owner TEXT NOT NULL, key TEXT NOT NULL)""")
    return store


def wave_key(identity, wave_id):
    return hashlib.sha256(
        canonical([identity.address, identity.actor, wave_id]).encode()
    ).hexdigest()


def owned_wave(db, identity, wave_id):
    row = db.execute(
        "SELECT * FROM provider_waves WHERE id=?", (wave_key(identity, wave_id),)
    ).fetchone()
    if row is None or row["owner"] != identity.address or row["actor"] != identity.actor:
        raise ValueError("provider wave requires its exact owner")
    return row


def record_operation(db, owner, key, request):
    bounded(key, "wave operation key")
    encoded = canonical(request)
    previous = db.execute(
        "SELECT request FROM provider_wave_operations WHERE owner=? AND key=?", (owner, key)
    ).fetchone()
    if previous:
        if previous["request"] != encoded:
            raise ValueError("wave operation key changed request")
        return True
    db.execute("INSERT INTO provider_wave_operations VALUES(?,?,?)", (owner, key, encoded))
    return False


def dispatch_snapshot(db, item, job):
    if job is None:
        return item["state"], ""
    if job["status"] in TERMINAL:
        return "terminal", ""
    has_leases = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='provider_worker_leases'"
    ).fetchone()
    lease = (
        db.execute(
            "SELECT state FROM provider_worker_leases WHERE run_id=?", (item["run_id"],)
        ).fetchone()
        if has_leases
        else None
    )
    if lease and lease["state"] == "active":
        return "worker-claimed", ""
    outbox = db.execute(
        "SELECT diagnostic FROM provider_wave_outbox WHERE run_id=?", (item["run_id"],)
    ).fetchone()
    if outbox is not None:
        return ("launch-failed" if outbox["diagnostic"] else "launch-pending"), outbox["diagnostic"]
    return job["status"], ""


def snapshot(db, row):
    request = json.loads(row["request"])
    entries = []
    for item in db.execute(
        "SELECT * FROM provider_wave_entries WHERE wave_id=? ORDER BY ordinal", (row["id"],)
    ):
        definition = request["entries"][item["ordinal"]]
        job = db.execute(
            "SELECT status,result FROM provider_jobs WHERE id=?", (item["run_id"],)
        ).fetchone()
        result = json.loads(job["result"]) if job and job["result"] else None
        terminal = job and job["status"] in TERMINAL
        dispatch_state, diagnostic = dispatch_snapshot(db, item, job)
        entries.append(
            {
                "entry_id": item["entry_id"],
                "depends_on": definition["depends_on"],
                "run_id": item["run_id"],
                "status": job["status"] if job else item["state"],
                "attempt": item["attempt"],
                "original_request": request_scope(definition["request"]),
                "attempts": [
                    json.loads(prior[0])
                    for prior in db.execute(
                        "SELECT record FROM provider_wave_attempts WHERE wave_id=? AND entry_id=? ORDER BY attempt",
                        (row["id"], item["entry_id"]),
                    )
                ],
                "dispatch_state": dispatch_state,
                "dispatch_diagnostic": diagnostic,
                "generation": result.get("worker_generation") if terminal and result else None,
                "result_digest": digest(result) if terminal and result else None,
                "result": result,
                "consumption": json.loads(item["consumption"]) if item["consumption"] else None,
            }
        )
    states = {e["entry_id"]: entry_state(e) for e in entries}
    pending_entries = [
        e
        for e in entries
        if not e["consumption"]
        and not (e["run_id"] is None and e["status"] in {"blocked", "cancelled"})
    ]
    return {
        "wave_id": row["public_id"],
        "owner": row["owner"],
        "task_scope": request["task_scope"],
        "workflow_id": request["workflow_id"],
        "max_parallel": request["max_parallel"],
        "capacity_basis": request["capacity_basis"],
        "cancel_requested": bool(row["cancel_requested"]),
        "blocked_reason": row["blocked_reason"],
        "entries": entries,
        "states": states,
        "pending": bool(pending_entries),
        "all_succeeded": all(state == "succeeded" for state in states.values()),
        "assurance": "agent-report",
        "provenance": "provider-peer",
    }

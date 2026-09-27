"""Atomic provider progress and terminal-result persistence.

A journal checks the current lease inside every write transaction. Routing and
terminal scheduling are application callbacks that run on that same connection;
notifications are emitted only by the transaction's existing after-commit hooks.
"""

import hashlib
import json
import time
from contextlib import nullcontext

from neurath.agents.lifecycle import TERMINAL, TaskLifecycle
from neurath.serialization import canonical


def finish(store, run_id, result, lease=None, *, bind_executor, on_terminal, db=None, tasks=None):
    if result["status"] not in TERMINAL:
        result = {**result, "provider_status": result["status"], "status": "failed"}
    from neurath.providers.job_recovery import archive_result

    tasks = tasks if tasks is not None else TaskLifecycle(store)
    with store.connection() if db is None else nullcontext(db) as db:
        if lease is not None:
            lease.assert_current(db)
        row = db.execute("SELECT * FROM provider_jobs WHERE id=?", (run_id,)).fetchone()
        owner = row["owner"]
        if row["status"] in TERMINAL and lease is None:
            return json.loads(row["result"])
        previous = json.loads(row["result"]) if row["result"] else {}
        if lease is not None and lease.generation > 1:
            previous = {
                k: v
                for k, v in previous.items()
                if k in {"created", "closure", "model_plan", "policy_inheritance"}
            }
        result = {**previous, **result}
        reply_recipient = bind_executor(store, row, result, lease, db)
        result["reply_route"] = {
            "status": "bound" if reply_recipient else "unavailable",
            "recipient": reply_recipient,
        }
        db.execute(
            "UPDATE provider_jobs SET status=?,result=?,updated=? WHERE id=?",
            (result["status"], canonical(result), time.time(), run_id),
        )
        task_key = (
            "provider:"
            + run_id
            + (
                ":recovery:" + str(lease.generation)
                if lease is not None and lease.generation > 1
                else ""
            )
        )
        task_id = hashlib.sha256(canonical([owner, task_key]).encode()).hexdigest()
        if lease is not None and lease.generation > 1:
            tasks.bind(owner, owner, key=task_key, transport="provider-recovery", _db=db)
        archive_result(db, run_id, lease.generation if lease is not None else 0, result)
        tasks.emit(
            owner,
            task_id,
            result["status"],
            key="terminal",
            detail=canonical(result).encode()[:15000].decode("utf-8", errors="ignore"),
            reply_recipient=reply_recipient,
            _db=db,
        )
        if lease is not None:
            db.execute(
                "UPDATE provider_worker_leases SET state='finished' WHERE run_id=? AND generation=? AND token=?",
                (run_id, lease.generation, lease.token),
            )
        on_terminal(store, db, run_id, result)
    return result


class JobEvents:
    """Persist one worker generation's events and exact assignment readiness."""

    def __init__(self, store, lease, owner, task_id, assignment, *, bind_executor, observe_created):
        self.store, self.lease = store, lease
        self.owner, self.task_id = owner, task_id
        self.assignment_digest = hashlib.sha256(assignment.encode()).hexdigest()
        self.bind_executor, self.observe_created = bind_executor, observe_created
        self.tasks = TaskLifecycle(store)
        self.sequence = 0

    def __call__(self, state, detail):
        self.sequence += 1
        run_id = self.lease.run_id
        with self.store.connection() as db:
            self.lease.assert_current(db)
            if state == "native-created":
                self.observe_created(self.store, self.lease, detail["created"], db)
                previous = db.execute(
                    "SELECT result FROM provider_jobs WHERE id=?", (run_id,)
                ).fetchone()[0]
                partial = json.loads(previous) if previous else {}
                partial.update(detail)
                partial["worker_generation"] = self.lease.generation
                db.execute(
                    "UPDATE provider_jobs SET result=?,updated=? WHERE id=?",
                    (canonical(partial), time.time(), run_id),
                )
                return
            current = db.execute("SELECT * FROM provider_jobs WHERE id=?", (run_id,)).fetchone()
            partial = json.loads(current["result"]) if current["result"] else {}
            reply_recipient = self.bind_executor(self.store, current, partial, self.lease, db)
            if state == "assignment-ready":
                if (
                    reply_recipient is None
                    or detail.get("assignment_digest") != self.assignment_digest
                ):
                    raise ValueError(
                        "prepared assignment lacks its owned native recipient or exact request"
                    )
                return  # A readback route, not another task, message or completion event.
            self.tasks.emit(
                self.owner,
                self.task_id,
                state,
                key=f"event:{self.sequence}",
                detail=canonical(detail).encode()[:15000].decode("utf-8", errors="ignore"),
                reply_recipient=reply_recipient,
                _db=db,
            )
            db.execute(
                "UPDATE provider_jobs SET status=?,updated=? WHERE id=?",
                (state, time.time(), run_id),
            )

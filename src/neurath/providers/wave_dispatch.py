"""Committed provider-wave outbox delivery and pre-native reconciliation.

The OS lock serializes launch scans. Worker leases remain the final execution
fence, and authority validation and terminal persistence are supplied explicitly
by the wave service. No native identity is reconstructed here.
"""

import fcntl
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from neurath.agents.runner import child_environment
from neurath.providers import jobs
from neurath.providers.job_recovery import JobRecovery, RecoveryUnavailable
from neurath.redaction import clean


def drain(store, wave_id, *, validate_scope, finish):
    """At-least-once launch from committed reservations; worker lease fences execution."""
    lock_path = store.directory / ("wave-" + hashlib.sha256(wave_id.encode()).hexdigest() + ".lock")
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    stranded = []
    try:
        # Runs outside DB transactions. Waiting for another drain preserves a
        # terminal event that enqueued work while the previous drain was active.
        fcntl.flock(fd, fcntl.LOCK_EX)
        recovery = JobRecovery(store)
        with store.connection() as db:
            run_ids = [
                r[0]
                for r in db.execute(
                    "SELECT e.run_id FROM provider_wave_entries e JOIN provider_jobs j ON j.id=e.run_id "
                    "WHERE e.wave_id=? AND (j.status IN ('accepted','starting') OR EXISTS "
                    "(SELECT 1 FROM provider_wave_outbox o WHERE o.run_id=e.run_id)) ORDER BY e.ordinal",
                    (wave_id,),
                )
            ]
        for run_id in run_ids:
            with store.connection() as db:
                wave = db.execute("SELECT * FROM provider_waves WHERE id=?", (wave_id,)).fetchone()
                job = db.execute("SELECT * FROM provider_jobs WHERE id=?", (run_id,)).fetchone()
                if job["status"] not in {"accepted", "starting"}:
                    db.execute("DELETE FROM provider_wave_outbox WHERE run_id=?", (run_id,))
                    continue
            try:
                initial, generation = recovery.pre_native_state(wave["owner"], run_id)
                if initial != "launch" or wave["cancel_requested"]:
                    stranded.append((wave["owner"], run_id, initial, generation))
                    continue
                with store.connection() as db:
                    validate_scope(store, db, json.loads(wave["request"])["task_scope"])
                fields = json.loads(job["request"])
                jobs.validate_target(store.worktree, fields)
                with (Path(job["control"]) / "worker.log").open("ab") as log:
                    jobs._launch(
                        [
                            sys.executable,
                            "-I",
                            "-m",
                            "neurath.providers.jobs",
                            "--root",
                            str(store.worktree),
                            "--run-id",
                            run_id,
                        ],
                        cwd=fields["worktree"],
                        env=child_environment(),
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=log,
                        start_new_session=True,
                    )
                with store.connection() as db:
                    db.execute(
                        "UPDATE provider_wave_outbox SET diagnostic='' WHERE run_id=?", (run_id,)
                    )
            except RecoveryUnavailable:
                continue
            except (OSError, ValueError) as error:
                with store.connection() as db:
                    db.execute(
                        "UPDATE provider_wave_outbox SET diagnostic=? WHERE run_id=?",
                        (clean(str(error)), run_id),
                    )
            # Keep the outbox until worker lease consumption is observable. A
            # lost Popen reply or process crash before claim remains retryable.
    finally:
        os.close(fd)
    # Closing an orphan can enqueue another drain. Release our wave lock first.
    for owner, run_id, reason, generation in stranded:
        close_initial(store, recovery, owner, run_id, reason, generation=generation, finish=finish)


def close_initial(store, recovery, owner, run_id, reason, *, generation=None, finish):
    def terminal(db, lease):
        cancelled = db.execute(
            "SELECT cancel_requested FROM provider_jobs WHERE id=?", (run_id,)
        ).fetchone()[0]
        return finish(
            store,
            run_id,
            {
                "run_id": run_id,
                "status": "cancelled" if cancelled else "failed",
                "diagnostic": "initial admission " + reason,
                "implementation_dispatched": False,
                "worker_generation": lease.generation,
                "execution": "unobserved",
                "native_creation": "unobserved",
            },
            lease,
            _db=db,
        )

    try:
        if generation is None:
            _, generation = recovery.pre_native_state(owner, run_id)
        recovery.finish_pre_native(owner, run_id, generation, terminal)
    except RecoveryUnavailable:
        pass

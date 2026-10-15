"""Explicit local-command host adapter, also useful for isolated host contract tests.

Selecting this adapter is the caller's decision under native execution permissions.
It provides no approval bypass, evaluator, shell interpolation or restart replay.
"""

import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from neurath.domain.workflows import Observation


class CommandHost:
    deduplicates = False

    def __init__(self, directory: Path, *, cancelled=None, notify=None):
        self.directory = directory.resolve()
        self.cancelled = cancelled or threading.Event()
        self._notify = notify or (lambda message: print(message, file=sys.stderr))

    def lookup(self, execution):
        # A subprocess without a durable external receipt cannot safely be replayed.
        return None

    def notify(self, execution, message):
        self._notify(f"Workflow {execution.run_id}, attempt {execution.id}: {message}")

    def execute(self, execution):
        phase = execution.phase
        process = subprocess.Popen(
            phase.action,
            cwd=self.directory,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        output = bytearray()
        total = 0

        def drain():
            nonlocal total
            assert process.stdout is not None
            try:
                while chunk := process.stdout.read(8192):
                    total += len(chunk)
                    output.extend(chunk[: max(0, phase.output_limit - len(output))])
            finally:
                process.stdout.close()

        reader = threading.Thread(target=drain, daemon=True)
        reader.start()
        deadline = time.monotonic() + phase.timeout
        outcome = None
        try:
            while process.poll() is None:
                if self.cancelled.is_set():
                    outcome = "interrupted"
                    break
                if time.monotonic() >= deadline:
                    outcome = "timed_out"
                    break
                time.sleep(min(0.01, max(0.001, deadline - time.monotonic())))
        except KeyboardInterrupt:
            outcome = "interrupted"
        finally:
            # Kill descendants too, including children keeping stdout open after the
            # leader exits. Do not leave a pipe-draining thread or orphan command.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            reader.join(timeout=2)
        outcome = outcome or ("succeeded" if process.returncode == 0 else "failed")
        summary = f"Command {outcome}; exit={process.returncode}; output_bytes={total}"
        if total > phase.output_limit:
            summary += "; stored output truncated"
        return Observation(
            "process-exit",
            outcome,
            summary,
            phase.target,
            phase.target_revision,
            (f"process:{execution.id}:exit:{process.returncode}",),
            satisfied=("execution",) if outcome == "succeeded" else (),
            output=output.decode("utf-8", errors="replace")[: phase.output_limit],
        )

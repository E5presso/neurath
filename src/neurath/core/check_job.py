"""Owned check process. Only an exact native-admitted profile command can run."""

import argparse
import os
import signal
import subprocess
from hashlib import sha256

from neurath.core.codec import encode
from neurath.core.commands import Context
from neurath.core.domain import require
from neurath.core.service import Core


def execute(definition):
    process = subprocess.Popen(
        definition["argv"],
        cwd=definition["cwd"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=definition.get("timeout_seconds"))
    except subprocess.TimeoutExpired, KeyboardInterrupt:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.communicate()
        raise
    survivors = False
    try:
        os.killpg(process.pid, 0)
        survivors = True
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    marker = definition.get("stdout_contains")
    return {
        "exit_code": process.returncode,
        "passed": not survivors
        and process.returncode in definition["success_codes"]
        and (marker is None or marker.encode() in stdout),
        "stdout": stdout[-16384:].decode(errors="replace"),
        "stderr": stderr[-16384:].decode(errors="replace"),
        "stdout_sha256": sha256(stdout).hexdigest(),
        "stderr_sha256": sha256(stderr).hexdigest(),
        "output_truncated": len(stdout) > 16384 or len(stderr) > 16384,
        "owned_processes_survived": survivors,
    }


def run(core, identifier):
    with core.store.transaction() as tx:
        record = tx.record("check-execution", identifier)
        require(
            record is not None and record["value"]["state"] == "admitted",
            "native-check-launch-required",
        )
        value = record["value"]
        task = tx.task(value["task_id"])
        require(task.state == "running", "task-state")
        task.validate_observation_scope(value["execution_scope"])
        task.require_participant(value["actor_id"])
        tx.put_record(
            "check-execution", identifier, {**value, "state": "running"}, record["revision"]
        )
    definition = value["definition"]
    try:
        result = execute(definition)
    except (OSError, subprocess.TimeoutExpired, KeyboardInterrupt) as error:
        with core.store.transaction() as tx:
            record = tx.record("check-execution", identifier)
            tx.put_record(
                "check-execution",
                identifier,
                {**record["value"], "state": "failed-to-execute", "error": type(error).__name__},
                record["revision"],
            )
        return {"state": "failed-to-execute", "error": type(error).__name__}
    context = Context(value["actor_id"], value["session_id"], "check-result:" + identifier)
    evidence = core.provenance.observe_tool(
        context,
        value["task_id"],
        "owned-check:" + identifier,
        result,
        kind="check",
        subject=value["subject"],
        checkout_path=value["checkout"],
        execution_scope=value["execution_scope"],
    )
    with core.store.transaction() as tx:
        record = tx.record("check-execution", identifier)
        tx.put_record(
            "check-execution",
            identifier,
            {**record["value"], "state": "completed", "result": result, "evidence_id": evidence.id},
            record["revision"],
        )
    return {"state": "completed", "result": result, "evidence_id": evidence.id}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--execution-id", required=True)
    args = parser.parse_args()
    result = run(Core(args.root), args.execution_id)
    print(encode(result), flush=True)
    return 0 if result.get("result", {}).get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())

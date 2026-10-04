"""Exact profile checks run in the native host and retain real process results."""

import shlex
import sys
from uuid import uuid4

from neurath.core.domain import require
from neurath.core.workspace import checkout, source_subject

COMMANDS = {
    "verification_prepare": ({"task_id", "checkout", "check_name"}, set(), False),
    "verification_read": ({"execution_id"}, set(), True),
}


def call(tx, core, context, name, values):
    if name == "verification_read":
        record = tx.record("check-execution", values["execution_id"])
        require(record is not None, "check-execution-missing")
        return {"execution": record["value"]}
    from neurath.core.hooks import configured_checks

    task = tx.task(values["task_id"])
    core._participant(task, context.actor_id)
    require(task.state == "running", "task-state")
    target = checkout(core.store.root, values["checkout"])
    definition = next(
        (item for item in configured_checks(target) if item["name"] == values["check_name"]), None
    )
    require(definition is not None, "check-definition-missing")
    identifier = "check-" + uuid4().hex
    command = shlex.join(
        [
            sys.executable,
            "-I",
            "-m",
            "neurath.core.check_job",
            "--root",
            str(core.store.root),
            "--execution-id",
            identifier,
        ]
    )
    value = {
        "id": identifier,
        "task_id": task.id,
        "actor_id": context.actor_id,
        "session_id": context.session_id,
        "checkout": target,
        "definition": definition,
        "command": command,
        "state": "prepared",
    }
    tx.put_record("check-execution", identifier, value)
    provider = core._actor(tx, context)["provider"]
    return {
        "execution": value,
        "native_action": {
            "tool": "Bash" if provider == "claude-code" else "exec_command",
            "arguments": {"command": command, "run_in_background": True}
            if provider == "claude-code"
            else {"cmd": command, "workdir": target, "yield_time_ms": 1000},
        },
        "instruction": "Execute once through the native host and wait using its returned process handle. Read the stored terminal result; printed JSON is not exit evidence.",
    }


def authorize_launch(core, context, payload):
    values = payload["tool_input"]
    command = values.get("command", values.get("cmd"))
    with core.store.transaction() as tx:
        candidates = [
            r for r in tx.records("check-execution") if r["value"].get("command") == command
        ]
        if not candidates:
            return False
        require(len(candidates) == 1, "check-execution-ambiguous")
        record = candidates[0]
        value = record["value"]
        require(
            value["state"] == "prepared"
            and value["actor_id"] == context.actor_id
            and value["session_id"] == context.session_id,
            "check-launch-state",
        )
        task = tx.task(value["task_id"])
        core._participant(task, context.actor_id)
        require(task.state == "running", "task-state")
        from neurath.core.hooks import configured_checks

        require(
            value["definition"] in configured_checks(value["checkout"]), "check-definition-changed"
        )
        native_id = payload.get("tool_use_id")
        require(isinstance(native_id, str) and native_id, "native-tool-id-required")
        tx.put_record(
            "check-execution",
            value["id"],
            {
                **value,
                "state": "admitted",
                "native_invocation": native_id,
                "subject": source_subject(value["checkout"]),
                "execution_scope": [list(item) for item in task.observation_scope()],
            },
            record["revision"],
        )
    return True

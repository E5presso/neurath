"""Prepare explicit independent/provider sessions for native-host execution."""

import shlex
import sys
from uuid import uuid4

from neurath.core.domain import require
from neurath.core.workspace import checkout

COMMANDS = {
    "provider_prepare": ({"task_id", "assignment_id", "checkout"}, {"model"}, False),
    "provider_read": ({"run_id"}, set(), True),
}


def call(tx, core, context, name, values):
    if name == "provider_read":
        record = tx.record("provider-run", values["run_id"])
        require(record is not None, "provider-run-missing")
        return {"run": record["value"]}
    task = tx.task(values["task_id"])
    assignment = next((a for a in task.assignments if a.id == values["assignment_id"]), None)
    require(assignment is not None and assignment.issuer == context.actor_id, "assignment-issuer")
    require(assignment.execution in {"session", "cross-provider"}, "provider-not-needed")
    require(assignment.state == "issued" and not assignment.recipient, "assignment-state")
    target = checkout(core.store.root, values["checkout"])
    dispatch = tx.record("dispatch", assignment.id)
    review_target = dispatch["value"].get("review_target")
    require(
        review_target is None or review_target["checkout"] == target, "review-checkout-mismatch"
    )
    require(dispatch["value"]["state"] == "prepared", "dispatch-already-started")
    require(
        values.get("model") is None or isinstance(values["model"], str) and values["model"].strip(),
        "model",
    )
    identifier = "run-" + uuid4().hex
    command = shlex.join(
        [
            sys.executable,
            "-I",
            "-m",
            "neurath.core.provider_job",
            "--root",
            str(core.store.root),
            "--run-id",
            identifier,
        ]
    )
    value = {
        "id": identifier,
        "task_id": task.id,
        "assignment_id": assignment.id,
        "issuer": context.actor_id,
        "provider": dispatch["value"]["provider"],
        "checkout": target,
        "model": values.get("model"),
        "execution": assignment.execution,
        "state": "prepared",
        "command": command,
        "native_session": None,
        "recipient": None,
    }
    tx.put_record("provider-run", identifier, value)
    tx.put_record(
        "dispatch",
        assignment.id,
        {**dispatch["value"], "state": "launch-prepared", "run_id": identifier},
        dispatch["revision"],
    )
    return {
        "run": value,
        "native_action": {
            "tool": "exec_command",
            "arguments": {"cmd": command, "workdir": target, "yield_time_ms": 1000},
        },
        "instruction": "Run this through the native host so its permissions remain effective. Prepared is not started or completed. No app project is created.",
    }


def authorize_launch(core, context, payload):
    from neurath.core.domain import admit_effects

    values = payload["tool_input"]
    command = values.get("command", values.get("cmd"))
    with core.store.transaction() as tx:
        candidates = [r for r in tx.records("provider-run") if r["value"]["command"] == command]
        if not candidates:
            return False
        require(len(candidates) == 1, "provider-run-ambiguous")
        record = candidates[0]
        value = record["value"]
        require(
            value["issuer"] == context.actor_id and value["state"] == "prepared",
            "provider-launch-state",
        )
        task = tx.task(value["task_id"])
        admit_effects(task, frozenset({"delegate"}))
        controllers = {
            a.recipient for a in task.assignments if a.role == "executor" and a.state == "active"
        }
        require(context.actor_id in (controllers or {task.owner_actor}), "assignment-issuer")
        native_id = payload.get("tool_use_id")
        require(isinstance(native_id, str) and native_id, "native-tool-id-required")
        tx.put_record(
            "provider-run",
            value["id"],
            {
                **value,
                "state": "admitted",
                "native_invocation": native_id,
                "issuer_session": context.session_id,
            },
            record["revision"],
        )
        return True


def observe_start(core, provider, context):
    from neurath.core.codec import encode

    with core.store.transaction() as tx:
        link = tx.record("provider-session", encode([provider, context.session_id]))
        if link is None:
            return
        record = tx.record("provider-run", link["value"]["run_id"])
        run = record["value"]
        if run["recipient"] is not None:
            require(run["recipient"] == context.actor_id, "recipient-rebinding")
            return
    core.bind_recipient(run["task_id"], run["assignment_id"], context.actor_id)
    core.call(
        context,
        "assignment_start",
        {
            "key": "provider-start:" + run["id"],
            "task_id": run["task_id"],
            "assignment_id": run["assignment_id"],
        },
    )
    with core.store.transaction() as tx:
        latest = tx.record("provider-run", run["id"])
        if latest["value"]["recipient"] == context.actor_id:
            return
        tx.put_record(
            "provider-run",
            run["id"],
            {
                **latest["value"],
                "recipient": context.actor_id,
                "native_session": context.session_id,
                "state": "connected",
            },
            latest["revision"],
        )


def input_origin(core, provider, session_id, prompt):
    from hashlib import sha256

    from neurath.core.codec import encode

    with core.store.transaction() as tx:
        link = tx.record("provider-session", encode([provider, session_id]))
        if link:
            run = tx.record("provider-run", link["value"]["run_id"])["value"]
            if run.get("prompt_digest") == sha256(prompt.encode()).hexdigest():
                return "peer"
    return "unknown"

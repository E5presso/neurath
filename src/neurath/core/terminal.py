"""Retained native terminal input is checked again against the current Task."""

from neurath.core.codec import encode
from neurath.core.domain import require
from neurath.core.host_events import effect_target, effects_for_tool, write_targets
from neurath.core.workspace import checkout


def control(values):
    return values.get("chars", "") in {"", "\x03"}


def observe(core, context, payload):
    response = payload.get("tool_response")
    if not isinstance(response, dict):
        return
    name, values = payload.get("tool_name"), payload.get("tool_input", {})
    handle = response.get("session_id")
    if name == "write_stdin":
        handle = values.get("session_id")
    if type(handle) is not int:
        return
    key = encode([context.actor_id, context.session_id, handle])
    with core.store.transaction() as tx:
        previous = tx.record("terminal", key)
        if name == "write_stdin":
            if previous and type(response.get("exit_code")) is int:
                tx.put_record(
                    "terminal", key, {**previous["value"], "active": False}, previous["revision"]
                )
        elif name in {"exec_command", "functions.exec_command", "functionsexec_command"}:
            directory = values.get("workdir") or values.get("cwd") or payload.get("cwd")
            if isinstance(directory, str):
                target = checkout(core.store.root, directory)
                tx.put_record(
                    "terminal",
                    key,
                    {"checkout": target, "active": True},
                    0 if previous is None else previous["revision"],
                )


def admit(core, context, values):
    if control(values):
        return
    require(isinstance(values.get("chars"), str), "terminal-input")
    key = encode([context.actor_id, context.session_id, values.get("session_id")])
    with core.store.transaction() as tx:
        record = tx.record("terminal", key)
        require(record is not None and record["value"]["active"], "native-terminal-unobserved")
        target = record["value"]["checkout"]
        lease = tx.lease(target)
    command = {"cmd": values["chars"], "workdir": target}
    effects = effects_for_tool("exec_command", command, cwd=target) | {"execute"}
    targets = {
        checkout(core.store.root, path) for path in write_targets("exec_command", command, target)
    } | {target}
    for destination in sorted(targets):
        with core.store.transaction() as tx:
            lease = tx.lease(destination)
        core.admit(
            context,
            effects,
            checkout_path=destination,
            generation=None if lease is None else lease["generation"],
            effect_target=effect_target("exec_command", command, target)
            if effects & {"publish", "decision"}
            else None,
        )

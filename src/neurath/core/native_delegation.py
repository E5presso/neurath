"""Correlate native child creation with an existing owner-issued assignment.

The marker selects a prepared record. Native issuer and child observations, not
marker text, bind its actors. Launches serialize only until their native start is
observed; the assigned work remains parallel.
"""

import re
from dataclasses import replace

from neurath.core.codec import encode
from neurath.core.domain import admit_effects, require

SPAWN = frozenset(
    {"spawn_agent", "collaborationspawn_agent", "collaboration.spawn_agent", "Agent", "Task"}
)
FOLLOWUP = frozenset({"followup_task", "collaborationfollowup_task", "collaboration.followup_task"})
MARKER = re.compile(r"\[neurath-assignment:(assignment-[a-f0-9]{32})\]")


def prepare(core, provider, context, payload):
    name, values = payload["tool_name"], payload["tool_input"]
    if name not in SPAWN | FOLLOWUP:
        return
    message = values.get("message", values.get("prompt", ""))
    require(isinstance(message, str), "assignment-message")
    markers = set(MARKER.findall(message))
    require(len(markers) == 1, "assignment-marker-required")
    identifier = markers.pop()
    native_id = payload.get("tool_use_id")
    require(isinstance(native_id, str) and bool(native_id), "native-tool-id-required")
    slot = encode([provider, context.session_id])
    with core.store.transaction() as tx:
        dispatch = tx.record("dispatch", identifier)
        require(
            dispatch is not None and dispatch["value"]["issuer"] == context.actor_id,
            "assignment-issuer",
        )
        task = tx.task(dispatch["value"]["task_id"])
        controllers = {
            a.recipient for a in task.assignments if a.role == "executor" and a.state == "active"
        }
        require(context.actor_id in (controllers or {task.owner_actor}), "assignment-issuer")
        admit_effects(task, frozenset({"delegate"}))
        assignment = next(a for a in task.assignments if a.id == identifier)
        require(
            assignment.execution == "subagent" and assignment.state == "issued",
            "execution-target-mismatch",
        )
        resuming = (
            provider == "claude-code" and name in {"Agent", "Task"} and bool(values.get("resume"))
        )
        if name in FOLLOWUP or resuming:
            handle = tx.record("native-handle", assignment.recipient)
            require(
                handle is not None
                and (
                    values.get("resume") == handle["value"].get("agent_id")
                    if resuming
                    else values.get("target") == handle["value"].get("task_name")
                ),
                "native-target-mismatch",
            )
        else:
            require(not assignment.recipient, "recipient-already-bound")
            if assignment.role == "reviewer" and provider == "codex":
                require(values.get("fork_turns") == "none", "fresh-review-context-required")
            pending = tx.record("native-spawn", slot)
            require(
                pending is None or pending["value"]["state"] == "observed", "native-spawn-pending"
            )
            tx.put_record(
                "native-spawn",
                slot,
                {
                    "assignment_id": identifier,
                    "task_id": task.id,
                    "issuer": context.actor_id,
                    "tool_use_id": native_id,
                    "state": "starting",
                },
                0 if pending is None else pending["revision"],
            )
        tx.put_record(
            "native-dispatch",
            encode([provider, context.session_id, context.actor_id, native_id]),
            {"assignment_id": identifier, "task_id": task.id},
        )
        tx.put_record(
            "dispatch",
            identifier,
            {**dispatch["value"], "state": "dispatched"},
            dispatch["revision"],
        )


def child_started(core, provider, context):
    slot = encode([provider, context.session_id])
    with core.store.transaction() as tx:
        pending = tx.record("native-spawn", slot)
        if pending is None or pending["value"]["state"] != "starting":
            return
        value = pending["value"]
        # A resumed known child must not consume another pending fresh spawn.
        if tx.record("native-handle", context.actor_id) is not None:
            return
    core.bind_recipient(value["task_id"], value["assignment_id"], context.actor_id)
    with core.store.transaction() as tx:
        latest = tx.record("native-spawn", slot)
        require(latest["value"] == value, "native-spawn-changed")
        tx.put_record(
            "native-handle",
            context.actor_id,
            {"agent_id": context.actor_id.split(":agent:", 1)[1]},
        )
        tx.put_record(
            "native-spawn",
            slot,
            {**value, "state": "observed", "recipient": context.actor_id},
            latest["revision"],
        )


def finished(core, provider, context, payload, *, failed=False):
    identity = encode([provider, context.session_id, context.actor_id, payload.get("tool_use_id")])
    with core.store.transaction() as tx:
        record = tx.record("native-dispatch", identity)
        if record is None:
            return
        value = record["value"]
        task = tx.task(value["task_id"])
        assignment = next(a for a in task.assignments if a.id == value["assignment_id"])
        response = payload.get("tool_response")
        if (
            assignment.recipient
            and isinstance(response, dict)
            and isinstance(response.get("task_name"), str)
        ):
            previous = tx.record("native-handle", assignment.recipient)
            tx.put_record(
                "native-handle",
                assignment.recipient,
                {
                    **({} if previous is None else previous["value"]),
                    "task_name": response["task_name"],
                },
                0 if previous is None else previous["revision"],
            )
        if failed and not assignment.recipient:
            pending = tx.record("native-spawn", encode([provider, context.session_id]))
            if pending and pending["value"]["assignment_id"] == assignment.id:
                tx.put_record(
                    "native-spawn",
                    encode([provider, context.session_id]),
                    {**pending["value"], "state": "observed", "failed": True},
                    pending["revision"],
                )
            updated = task.with_assignment(replace(assignment, state="rejected", verdict="failed"))
            tx.save_task(updated, expected_revision=task.revision)

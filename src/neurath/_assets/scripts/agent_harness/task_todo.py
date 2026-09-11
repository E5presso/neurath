"""Native TODO submission receipts project task truth without creating it."""
import json

from .task_ledger import TaskLedgerError, _digest, _json

TOOLS = {"codex": "update_plan", "claude-code": "TodoWrite"}
TOOL_NAMES = frozenset({"update_plan", "functions.update_plan", "TodoWrite"})


def projection(ledger, host):
    tool = TOOLS.get(host)
    if tool is None:
        return None
    rows, active_shown = [], False
    for task in ledger.tasks:
        status = task.status.value
        # Both hosts use three visual states. Preserve every terminal outcome
        # and parallel running task explicitly in readable text.
        display = {"pending": "Pending", "in_progress": "In progress", "succeeded": "Succeeded",
                   "failed": "Failed", "invalidated": "Invalidated"}[status]
        native = "completed" if task.status.terminal else "pending"
        if status == "in_progress" and not active_shown:
            native, active_shown = "in_progress", True
        content = f"[Neurath] {task.definition.title} ({display}; {task.id}; list {ledger.revision})"
        rows.append({"id": task.id, "status": status, "content": content, "native": native})
    if host == "codex":
        arguments = {"plan": [{"step": row["content"], "status": row["native"]} for row in rows]}
    else:
        arguments = {"todos": [{"content": row["content"], "activeForm": row["content"],
                               "status": row["native"]} for row in rows]}
    return {"tool": tool, "arguments": arguments, "list_revision": ledger.revision,
            "projection_digest": _digest([ledger.session, ledger.owner, ledger.revision, rows]),
            "task_ids": [row["id"] for row in rows]}


def instruction(tx, process, ledger):
    candidate = projection(ledger, process.session.runtime.value)
    if candidate is None:
        return {"availability": "unsupported-runtime"}
    capability = tx.get(f"task-todo-capability:{ledger.session}", ledger.owner)
    return {"availability": "observed-supported" if capability else "unobserved",
            **candidate, "receipt_scope": "native-tool-submission"}


def record(tx, process, actor_id, host, payload, *, succeeded=None):
    """Receive only a host-bound root event inside the session transaction."""
    from .task_service import read_ledger
    from .session_kernel import ActorStatus, ForegroundTurnStatus, SessionStatus
    if actor_id != process.session.root_actor_id or host != process.session.runtime.value:
        return False
    tool = payload.get("tool_name", "").removeprefix("functions.")
    if tool != TOOLS.get(host):
        return False
    inputs = payload.get("tool_input")
    rows = inputs.get("plan" if host == "codex" else "todos") if isinstance(inputs, dict) else None
    recognized = isinstance(rows, list) and any(isinstance(row, dict) and
        str(row.get("step" if host == "codex" else "content", "")).startswith("[Neurath] ") for row in rows)
    _, ledger = read_ledger(tx, process)
    capability_ns = f"task-todo-capability:{ledger.session}"
    capability = tx.get(capability_ns, ledger.owner)
    if not recognized and capability is None:
        return False
    actor = process.actors.get(actor_id)
    turn = process.foreground_turns.get(actor_id)
    if (process.session.status is not SessionStatus.ACTIVE or actor is None
            or actor.status is not ActorStatus.ACTIVE or turn is None
            or turn.status not in {ForegroundTurnStatus.ACTIVE, ForegroundTurnStatus.READY_TO_STOP}):
        raise TaskLedgerError("native TODO submission requires an active root turn")
    invocation = payload.get("tool_use_id")
    if not isinstance(invocation, str) or not invocation:
        raise TaskLedgerError("native TODO event requires its host invocation ID")
    namespace = f"task-todo-attempt:{ledger.session}"
    prior = tx.get(namespace, invocation)
    expected = projection(ledger, host)
    request_digest = _digest(inputs)
    if succeeded is None:
        if not ledger.tasks or inputs != expected["arguments"]:
            raise TaskLedgerError("native TODO input differs from the full current task list")
        value = {"host": host, "tool": tool, "owner": ledger.owner,
                 "list_revision": ledger.revision, "projection_digest": expected["projection_digest"],
                 "task_ids": expected["task_ids"], "invocation_id": invocation,
                 "request_digest": request_digest, "status": "submitted"}
        if prior is not None:
            old = json.loads(prior.payload)
            if any(old.get(key) != item for key, item in value.items() if key != "status"):
                raise TaskLedgerError("native TODO invocation identity changed")
            return True
        tx.put(namespace, invocation, _json(value), expected_revision=None)
        if capability is None:
            tx.put(capability_ns, ledger.owner, _json({"host": host, "tool": tool}), expected_revision=None)
        return True
    if prior is None:
        raise TaskLedgerError("native TODO result lacks its prepared host request")
    value = json.loads(prior.payload)
    if (value["request_digest"] != request_digest or value["host"] != host or value["tool"] != tool):
        raise TaskLedgerError("native TODO result substituted its original request")
    outcome = "succeeded" if succeeded else "failed"
    if value["status"] != "submitted":
        if value.get("outcome") != outcome:
            raise TaskLedgerError("native TODO result contradicts its earlier receipt")
        return True
    current = value["projection_digest"] == expected["projection_digest"]
    value = {**value, "outcome": outcome,
             "status": "current" if succeeded and current else "stale" if succeeded else "failed"}
    tx.put(namespace, invocation, _json(value), expected_revision=prior.revision)
    if value["status"] == "current":
        published_ns = f"task-todo-projection:{ledger.session}"
        previous = tx.get(published_ns, ledger.owner)
        tx.put(published_ns, ledger.owner, _json(value),
               expected_revision=None if previous is None else previous.revision)
    return True

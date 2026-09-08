"""Strict assertions over actual native events and canonical readback.

A model's final narrative is never a tool-execution receipt. Callers preserve the
raw streams and pass only one intended thread/turn, not aggregated successful runs.
"""

import json
import shlex
from pathlib import Path


def _standalone_argv(command, depth=0):
    """Read a single native command, optionally inside the host's shell envelope."""
    if not isinstance(command, str) or depth > 8:
        return ()
    quote = None
    escaped = False
    for char in command:
        if escaped:
            escaped = False
            continue
        if char == "\\" and quote != "'":
            escaped = True
        elif quote:
            if char == quote:
                quote = None
        elif char in ("'", '"'):
            quote = char
        elif char in "\n\r":
            return ()
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|()<>")
        lexer.whitespace_split = True
        tokens = tuple(lexer)
    except ValueError:
        return ()
    if any(token and all(c in ";&|()<>" for c in token) for token in tokens):
        return ()
    if (len(tokens) == 3 and Path(tokens[0]).name in {"sh", "bash", "zsh", "dash", "ksh"}
            and tokens[1] in {"-c", "-lc", "-ic", "-lic"}):
        return _standalone_argv(tokens[2], depth + 1)
    return tokens


def _exact_command(actual, expected):
    required = _standalone_argv(expected)
    return bool(required) and _standalone_argv(actual) == required


def _checkpoint_saved(item, thread):
    """Accept a native CLI or named MCP receipt, never a model's save claim."""
    if (item.get("type") == "commandExecution"
            and _standalone_argv(item.get("command", ""))[:3] == (".neurath/run", "memory", "checkpoint")
            and item.get("exitCode") == 0):
        try:
            receipt = json.loads(item.get("aggregatedOutput", ""))
        except (ValueError, TypeError):
            return False
    elif (item.get("type") == "mcpToolCall" and item.get("server") == "neurath_collaboration"
            and item.get("tool") == "memory_checkpoint" and item.get("status") == "completed"
            and not item.get("error")):
        result = item.get("result")
        if not isinstance(result, dict) or result.get("isError"):
            return False
        body = result.get("structuredContent")
        if (not isinstance(body, dict) or body.get("ok") is not True
                or body.get("operation") != "memory_checkpoint"):
            return False
        receipt = body.get("result")
    else:
        return False
    return (isinstance(receipt, dict) and receipt.get("status") == "saved"
            and receipt.get("host") == "codex" and receipt.get("session") == thread
            and receipt.get("authority") == "agent-report"
            and isinstance(receipt.get("id"), str) and len(receipt["id"]) == 64
            and all(char in "0123456789abcdef" for char in receipt["id"]))


def codex_turn(
    events, thread, turn, commands=(), *, compact=False, protected_denial=False, checkpoint=False
):
    selected = [e for e in events if e.get("params", {}).get("threadId") == thread]
    endings = [
        e["params"]["turn"]
        for e in selected
        if e.get("method") == "turn/completed" and e["params"]["turn"]["id"] == turn
    ]
    assert (
        len(endings) == 1 and endings[0]["status"] == "completed" and not endings[0].get("error")
    ), "exact turn did not complete"
    scoped = [e for e in selected if e.get("params", {}).get("turnId") == turn]
    items = [e["params"]["item"] for e in scoped if e.get("method") == "item/completed"]
    hooks = [e["params"]["run"] for e in scoped if e.get("method") == "hook/completed"]
    blocked = [
        h
        for h in hooks
        if h.get("status") not in ("completed", "skipped")
        or any(x.get("kind") in ("block", "error", "stop") for x in h.get("entries", []))
    ]
    expected = [
        h
        for h in blocked
        if h.get("eventName") == "preToolUse" and "protected-capability" in json.dumps(h)
    ]
    handoffs = []
    if checkpoint:
        for index, event in enumerate(scoped):
            if event.get("method") != "hook/completed":
                continue
            hook = event["params"]["run"]
            if (
                hook not in blocked
                or hook.get("eventName") != "stop"
                or "Neurath needs a durable handoff before this turn ends." not in json.dumps(hook)
            ):
                continue
            saved = False
            for later in scoped[index + 1 :]:
                if later.get("method") == "item/completed":
                    saved = saved or _checkpoint_saved(later["params"]["item"], thread)
                if saved and later.get("method") == "hook/completed":
                    retry = later["params"]["run"]
                    if (
                        retry.get("eventName") == "stop"
                        and retry.get("status") == "completed"
                        and not any(
                            entry.get("kind") in ("block", "error", "stop")
                            for entry in retry.get("entries", [])
                        )
                    ):
                        handoffs.append(hook)
                        break
    assert len(blocked) == len(handoffs) + (len(expected) if protected_denial else 0), (
        "unexpected hook/admission failure"
    )
    if protected_denial:
        assert expected, "expected native protection hook denial was not observed"
    if compact:
        assert any(i["type"] == "contextCompaction" for i in items), (
            "no compaction item in exact completed turn"
        )
    for command, marker in commands:
        executed = [
            i
            for i in items
            if i.get("type") == "commandExecution"
            and _exact_command(i.get("command", ""), command)
            and i.get("exitCode") == 0
            and marker in (i.get("aggregatedOutput") or "")
        ]
        assert executed, f"no successful tool execution with expected marker: {command}"
    return {
        "turn": turn,
        "commands_checked": len(commands),
        "protected_denials": len(expected),
        "checkpoints": len(handoffs),
        "completed": True,
    }


def workflow_closed(state):
    workflow = state["workflows"]["live-validation"]
    assert workflow["status"] == "completed"
    root = state["session"]["root_actor_id"]
    assert state["foreground_turns"][root]["status"] == "closed"
    assert state["resources"]["worktrees"] == {}
    reports = state["delegations"]
    assert reports["live-draft"]["status"] == reports["live-evaluator"]["status"] == "consumed"
    child = reports["live-evaluator"]["target_actor_id"]
    assert state["actors"][child]["lineage_assurance"] == "host-attested"
    assert state["actors"][child]["parent_actor_id"] == root
    assert state["actors"][child]["status"] == "stopped"
    assert (
        reports["live-draft"]["result"]["outcome_ref"]
        == reports["live-evaluator"]["result"]["outcome_ref"]
    )
    batch = state["material_actions"][root]
    assert batch["resolution"] == "completed" and batch["invocations"]
    return {
        "workflow": "completed",
        "claim_absent": True,
        "evaluator": child,
        "outcome_ref": reports["live-evaluator"]["result"]["outcome_ref"],
    }


def claude_commands(events, commands):
    results = [e for e in events if e.get("type") == "result"]
    assert results and all(
        not r.get("is_error") and r.get("subtype") == "success" for r in results
    ), "native Claude result failed"
    calls = {}
    outputs = {}
    for event in events:
        content = event.get("message", {}).get("content", [])
        if not isinstance(content, list):
            continue
        for block in content:
            if block.get("type") == "tool_use":
                calls[block["id"]] = block
            if block.get("type") == "tool_result":
                outputs[block["tool_use_id"]] = block
    for command, marker in commands:
        matches = [
            (key, call)
            for key, call in calls.items()
            if call.get("name") == "Bash"
            and _exact_command(call.get("input", {}).get("command", ""), command)
        ]
        assert any(
            key in outputs
            and not outputs[key].get("is_error")
            and marker in json.dumps(outputs[key].get("content"))
            for key, call in matches
        ), f"Claude helper did not execute successfully: {command}"
    return {"commands_checked": len(commands), "result": "success"}


def observed_open_batch(state):
    batch = state.get("material_actions", {}).get(state["session"]["root_actor_id"], {})
    invocations = batch.get("invocations", [])
    return (
        batch.get("status") == "open"
        and bool(invocations)
        and all(i.get("status") == "observed" and i.get("receipt") is not None for i in invocations)
    )


def claude_background_completion(events, command, state):
    import re

    session = state.get("session", {}).get("id")
    assert session, "canonical native session unavailable"
    calls = {}
    for index, event in enumerate(events):
        if event.get("session_id") != session or event.get("type") != "assistant":
            continue
        content = event.get("message", {}).get("content", [])
        if not isinstance(content, list):
            continue
        for block in content:
            if block.get("type") == "tool_use":
                calls[block["id"]] = (index, block)
    starts = [
        (key, index)
        for key, (index, call) in calls.items()
        if call.get("name") == "Bash"
        and _exact_command(call.get("input", {}).get("command", ""), command)
        and call["input"].get("run_in_background") is True
    ]
    assert len(starts) == 1, "missing exact background helper execution"
    start_id, start_index = starts[0]
    tasks = [
        (index, event["task_id"])
        for index, event in enumerate(events)
        if index > start_index and event.get("type") == "system"
        and event.get("subtype") == "task_started"
        and event.get("session_id") == session and event.get("tool_use_id") == start_id
        and event.get("is_backgrounded") is True and event.get("task_type") == "local_bash"
        and event.get("task_id")
    ]
    assert len(tasks) == 1, "missing exact native background task start"
    task_index, task_id = tasks[0]
    texts = []
    for index, event in enumerate(events):
        if event.get("type") != "user" or event.get("session_id") != session:
            continue
        content = event.get("message", {}).get("content", [])
        if not isinstance(content, list):
            continue
        for block in content:
            if block.get("type") != "tool_result" or block.get("is_error"):
                continue
            call_index, call = calls.get(block.get("tool_use_id"), (-1, {}))
            if not (task_index < call_index < index and call.get("name") == "TaskOutput"
                    and call.get("input", {}).get("task_id") == task_id):
                continue
            # This is host metadata, never text parsed from Read or tool_result.content.
            result = event.get("tool_use_result", {})
            task = result.get("task", {}) if isinstance(result, dict) else {}
            if (result.get("retrieval_status") == "success" and task.get("task_id") == task_id
                    and task.get("task_type") == "local_bash" and task.get("status") == "completed"
                    and type(task.get("exitCode")) is int and task["exitCode"] == 0
                    and isinstance(task.get("output"), str)):
                texts.append(task["output"])
    assert texts, "background helper native numeric exit and output were not observed"
    records = []
    for text in texts:
        for line in text.splitlines():
            line = re.sub(r"^\s*\d+[→\t]\s*", "", line)
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict):
                records.append(record)
    assert any(
        r.get("premature_completion_rejected") == "AdaptiveControlAuthorityNotFound"
        for r in records
    )
    completed = [
        r
        for r in records
        if r.get("status") == "completed"
        and r.get("independent_authority") is True
        and r.get("decision") == "complete"
    ]
    assert completed, "no actual exact COMPLETE helper record"
    record = completed[-1]
    final = state["delegations"]["live-evaluator"]
    assignment = json.loads(final["assignment"])
    assert record["candidate_ref"] == assignment["candidate_ref"]
    assert record["outcome_ref"] == final["result"]["outcome_ref"]
    assert record["session_id"] == state["session"]["id"]
    return {
        "exit_code": 0,
        "candidate_ref": record["candidate_ref"],
        "outcome_ref": record["outcome_ref"],
        "task_id": task_id,
    }

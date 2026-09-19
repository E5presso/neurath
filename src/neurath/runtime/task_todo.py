"""Host events are the only producer of native TODO submission evidence."""
from pathlib import Path
import json


def remind(root, host, payload, output):
    """Surface an undisplayed ledger revision once on the next ordinary tool call."""
    from neurath.agents.hooks import native_peer
    from neurath.runtime.database import RuntimeDatabase
    from scripts.agent_harness.session_kernel import SessionLocator
    from scripts.agent_harness.task_service import read_ledger
    from scripts.agent_harness.task_todo import instruction, TOOL_NAMES

    tool = payload.get("tool_name", "")
    if (payload.get("hook_event_name") != "PreToolUse" or payload.get("agent_id")
            or tool in TOOL_NAMES or tool.startswith("mcp__neurath_collaboration__task_")):
        return output
    peer = native_peer(root, host, payload)
    if peer is None or not peer[0].is_root:
        return output
    identity, process, _ = peer
    locator = SessionLocator.from_worktree(Path(root))
    with RuntimeDatabase(locator.control_root).transaction() as tx:
        _, ledger = read_ledger(tx, process)
        todo = instruction(tx, process, ledger)
        if todo.get("display_status") != "pending":
            return output
        namespace = f"task-todo-reminder:{ledger.session}"
        previous = tx.get(namespace, ledger.owner)
        digest = todo["projection_digest"]
        if previous and previous.payload == digest.encode():
            return output
        tx.put(namespace, ledger.owner, digest.encode(),
               expected_revision=None if previous is None else previous.revision)
    encoded = json.dumps({"tool": todo["tool"], "arguments": todo["arguments"]}, ensure_ascii=False)
    action = encoded if len(encoded.encode()) <= 12000 else "Call task_list and use its exact native_todo arguments."
    notice = ("Neurath TODO display is pending for task list revision " + str(todo["list_revision"])
              + ". Update the native TODO now without waiting for the user to ask. "
                "Record concrete completed or newly discovered work with task tools as it happens; "
                "one umbrella task must not hide independently verifiable progress.\n" + action)
    result = dict(output)
    specific = dict(result.get("hookSpecificOutput", {}))
    specific.setdefault("hookEventName", payload["hook_event_name"])
    existing = specific.get("additionalContext", "")
    specific["additionalContext"] = existing + ("\n\n" if existing else "") + notice
    result["hookSpecificOutput"] = specific
    return result


def host_event(root, host, payload, raw):
    from neurath.agents.hooks import native_peer
    from neurath.runtime.database import RuntimeDatabase
    from scripts.agent_harness.session_kernel import SessionLocator, SessionStateStore
    from scripts.agent_harness.task_todo import record
    from scripts.agent_harness.tool_action_parser import ToolActionParser
    peer = native_peer(root, host, payload)
    if peer is None:
        return False
    identity, _, actor = peer
    if not identity.is_root:
        return False
    locator = SessionLocator.from_worktree(Path(root))
    state_store = SessionStateStore(locator.locate(identity.session).process_state)
    explicit_failure = any(isinstance(value, dict) and (
        value.get("success") is False or value.get("isError") is True)
        for value in (payload, *(payload.get(key) for key in (
            "tool_response", "tool_result", "tool_output", "result"))))
    succeeded = None if payload["hook_event_name"] == "PreToolUse" else (
        payload["hook_event_name"] == "PostToolUse" and not explicit_failure and
        ToolActionParser().parse_result(raw, Path(root)).succeeded)
    with RuntimeDatabase(locator.control_root).transaction() as tx:
        process = state_store.read_transaction(tx, identity.session)
        return record(tx, process, actor.id, host, payload, succeeded=succeeded)

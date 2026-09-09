"""Host events are the only producer of native TODO submission evidence."""
from pathlib import Path


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

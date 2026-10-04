"""Native payload identity, effects and stop responses share the core contract."""

import pytest

from neurath.core.domain import CoreError
from neurath.core.host_events import context_from_event, stop_response


def test_codex_child_uses_agent_id_not_parent_session_or_cwd():
    payload = {"session_id": "s", "agent_id": "child", "cwd": "/first", "tool_use_id": "tool"}
    first = context_from_event("codex", payload, "receipt")
    second = context_from_event("codex", {**payload, "cwd": "/second"}, "receipt")
    assert first == second
    assert first.actor_id == "codex:agent:child"
    assert first.session_id == "s"
    assert first != context_from_event("codex", {"session_id": "s"}, "receipt")


def test_missing_native_session_is_not_invented():
    with pytest.raises(CoreError, match="native-session-required"):
        context_from_event("claude-code", {"cwd": "/project"}, "receipt")


def test_stop_blocks_unfinished_task_without_claiming_host_shutdown_control():
    pending = {"allowed": False, "pending": [{"task_id": "task-1", "reason": "task-unfinished"}]}
    response = stop_response(pending)
    assert response["decision"] == "block"
    assert "task-1" in response["reason"]
    assert stop_response({"allowed": True, "pending": []}) == {}


def test_native_input_is_not_a_human_attestation(tmp_path):
    from neurath.core.service import Context, Core

    core = Core(tmp_path)
    core.observe_actor("root", "session", "codex")
    context = Context("root", "session", "event")
    first = core.observe_input(context, "Continue", "event-1", origin="continuation")
    second = core.observe_input(context, "Continue", "event-2")
    assert first.kind == "native_input"
    assert first.id != second.id
    assert core.observe_input(context, "Continue", "event-1", origin="continuation") == first
    with pytest.raises(CoreError, match="human-attestation-required"):
        core.observe_input(context, "Approved", "event-3", origin="human")
    with pytest.raises(CoreError, match="source-conflict"):
        core.observe_input(context, "Changed", "event-1")

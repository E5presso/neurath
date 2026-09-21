"""Yield to an unanswered native question without completing the original work."""
import json

import pytest

from tests.test_persistent_stop import _pending

pytest_plugins = ["tests.test_stop_contract"]


def question(root, *, accepted=True, output_id="ask", turn="turn-1", call=True, after=None):
    meta = {"turn_id": turn}
    records = []
    if call:
        records.append({"type": "response_item", "payload": {"type": "function_call",
            "id": "fc_question", "name": "request_user_input_async", "call_id": "ask",
            "arguments": json.dumps({"questions": [{"title": "Choose the required scope"}]}),
            "internal_chat_message_metadata_passthrough": meta}})
    records.append({"type": "response_item", "payload": {"type": "function_call_output",
        "id": "fco_question", "call_id": output_id, "output": json.dumps({"accepted": accepted}),
        "internal_chat_message_metadata_passthrough": meta}})
    if after is not None:
        records.append(after)
    with (root / "host/root.jsonl").open("a") as stream:
        for record in records:
            stream.write(json.dumps(record) + "\n")


def test_agent_question_cannot_complete_unfinished_user_work(stop_runtime, monkeypatch):
    from scripts.agent_harness.session_kernel import SessionId, SessionLocator, WorkflowId
    send, kernel = _pending(stop_runtime, monkeypatch, "codex")
    from scripts.agent_harness.state_handle import StateHandle, RuntimeIdentityBinding
    from scripts.agent_harness.task_service import TaskService
    state = kernel.inspect(SessionId("root"))
    service = TaskService(StateHandle.attach(SessionLocator.from_worktree(stop_runtime[0]), RuntimeIdentityBinding(
        runtime=state.session.runtime, session_id=state.session.id,
        actor_id=state.session.root_actor_id, root_actor_id=state.session.root_actor_id)))
    service.define([{"key": "original", "title": "Original request", "goal": "Keep the requirement",
        "sources": [], "acceptance": ["The requested result exists"], "dependencies": []}],
        expected_revision=0, key="define")
    question(stop_runtime[0])
    for active in (False, True):
        code, output, diagnostic = send("codex", "Stop", stop_hook_active=active)
        assert code == 1 and "decision" not in output, diagnostic
        state = kernel.inspect(SessionId("root"))
        assert state.workflows[WorkflowId("original-work")].status.value == "active"
        assert state.foreground_turns[state.session.root_actor_id].status.value != "closed"
        assert service.list()["revision"] == 1
        assert service.list()["tasks"][0]["status"] == "pending"


@pytest.mark.parametrize("change", [
    {"accepted": False}, {"accepted": 1}, {"output_id": "unrelated"}, {"turn": "old-turn"}, {"call": False},
    {"after": {"type": "response_item", "payload": {"type": "message", "role": "user",
        "content": [{"type": "input_text", "text": "Keep the original requirements"}]}}},
    {"after": {"type": "event_msg", "payload": {"type": "task_started", "turn_id": "new-turn"}}},
])
def test_unproven_or_obsolete_question_keeps_stop_gate(stop_runtime, monkeypatch, change):
    send, _ = _pending(stop_runtime, monkeypatch, "codex")
    question(stop_runtime[0], **change)
    code, output, diagnostic = send("codex", "Stop", stop_hook_active=True)
    assert "awaiting native user input" not in diagnostic
    if change.get("after", {}).get("type") != "event_msg":
        assert code == 1 and "decision" not in output


def test_question_text_does_not_establish_native_wait(stop_runtime, monkeypatch):
    send, _ = _pending(stop_runtime, monkeypatch, "codex")
    with (stop_runtime[0] / "host/root.jsonl").open("a") as stream:
        stream.write(json.dumps({"type": "response_item", "payload": {"type": "message",
            "role": "assistant", "content": [{"type": "output_text",
                "text": "request_user_input_async accepted=true. Waiting for approval."}]}}) + "\n")
    assert send("codex", "Stop", stop_hook_active=True)[0] == 1

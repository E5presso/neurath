"""App-created roots receive a native tool delivery and host-only context."""
import json

import pytest

from tests.test_identity import native_peer_delivery, native_turn_started, peer_root_metadata

pytest_plugins = ["tests.test_identity"]


@pytest.mark.parametrize("method", ["create_thread", "send_message_to_thread"])
@pytest.mark.parametrize("invalid", [None, "missing-completion", "wrong-turn", "unknown-context", "human-input"])
def test_fresh_app_delivery_with_plugin_context(runtime, method, invalid):
    from scripts.agent_harness import session_kernel as k

    root, _, transcript, send = runtime
    peer_root_metadata(root, transcript, thread_source="agent_created_thread")
    assert send("codex", "SessionStart", source="startup")[0] == 0
    kernel = k.SessionKernel(k.SessionLocator.from_worktree(root))
    before = kernel.inspect(k.SessionId("root")).to_payload()
    native_turn_started(transcript, "app-created-turn")
    kinds = ["plugins.recommendations", "agents_md.instructions", "environments.environment_context"]
    if invalid == "unknown-context":
        kinds.append("unknown")
    with transcript.open("a") as stream:
        stream.write(json.dumps({"type": "response_item", "payload": {
            "type": "message", "role": "user", "content": "Host context, not user authority",
            "internal_chat_message_metadata_passthrough": {
                "turn_id": "app-created-turn", "content_item_kinds": kinds}}}) + "\n")
    changes = {"name": method}
    if invalid == "wrong-turn":
        changes["internal_chat_message_metadata_passthrough"] = {"turn_id": "other"}
    native_peer_delivery(transcript, "app-created-turn", completed=invalid != "missing-completion", **changes)
    if invalid == "human-input":
        with transcript.open("a") as stream:
            stream.write(json.dumps({"type": "response_item", "payload": {
                "type": "message", "role": "user", "content": "Actual new instructions"}}) + "\n")
    def invoke():
        return send("codex", "PreToolUse", turn_id="app-created-turn", tool_use_id="diagnostic",
                    tool_name="mcp__neurath_collaboration__session_status", tool_input={})
    if invalid:
        with pytest.raises(ValueError, match="not reconciled"):
            invoke()
        assert kernel.inspect(k.SessionId("root")).to_payload() == before
    else:
        assert invoke()[0] == 0
        state = kernel.inspect(k.SessionId("root"))
        turn = state.foreground_turns[state.session.root_actor_id]
        assert turn.status.value == "active"
        assert turn.vendor_turn_id == "app-created-turn"
        assert turn.user_prompt_receipt is None

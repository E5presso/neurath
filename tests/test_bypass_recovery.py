"""Recover missed human turns from host provenance after bypass is disabled."""
import hashlib
import json

import pytest

from neurath.hosts.hooks import hook
from neurath.runtime.bypass import mode
from tests.test_identity import native_turn_started, native_user_text, peer_root_metadata

pytest_plugins = ["tests.test_identity"]


def skipped_prompt(runtime):
    from scripts.agent_harness import session_kernel as k

    root, _, transcript, send = runtime
    peer_root_metadata(root, transcript)
    native_turn_started(transcript, "original")
    native_user_text(transcript, "original", "Original work")
    assert send("codex", "SessionStart", source="startup")[0] == 0
    assert send("codex", "UserPromptSubmit", turn_id="original", prompt="Original work")[0] == 0
    kernel = k.SessionKernel(k.SessionLocator.from_worktree(root))
    state = kernel.inspect(k.SessionId("root"))
    kernel.apply(k.WorkflowStarted(session_id=state.session.id,
        workflow_id=k.WorkflowId("unfinished"), owner_actor_id=state.session.root_actor_id,
        kind="checkpoint", goal="Preserve original work", payload={}, idempotency_key="original-work"))
    mode(root, True)
    native_turn_started(transcript, "current")
    native_user_text(transcript, "current", "Repair the harness")
    assert send("codex", "UserPromptSubmit", turn_id="current", prompt="Repair the harness") == (0, {}, "")
    before = kernel.inspect(k.SessionId("root"))
    assert before.foreground_turns[before.session.root_actor_id].vendor_turn_id == "original"
    mode(root, False)
    payload = {"hook_event_name": "PreToolUse", "session_id": "root", "cwd": str(root),
        "transcript_path": str(transcript), "turn_id": "current", "tool_use_id": "recover",
        "tool_name": "mcp__neurath_collaboration__session_status", "tool_input": {}}
    return kernel, before, payload


def test_first_tool_after_bypass_recovers_current_native_user_turn(runtime):
    from scripts.agent_harness import session_kernel as k

    root, _, _, _ = runtime
    kernel, before, payload = skipped_prompt(runtime)
    code, output, diagnostic = hook(root, "codex", json.dumps(payload), {"CODEX_THREAD_ID": "root"})
    assert code == 0, diagnostic
    assert output["hookSpecificOutput"]["updatedInput"]["_neurath_binding"]
    state = kernel.inspect(before.session.id)
    turn = state.foreground_turns[state.session.root_actor_id]
    assert turn.vendor_turn_id == "current"
    assert turn.generation == before.foreground_turns[before.session.root_actor_id].generation + 1
    assert turn.user_prompt_receipt.prompt_digest == hashlib.sha256(b"Repair the harness").hexdigest()
    assert state.workflows[k.WorkflowId("unfinished")].to_payload() == before.workflows[k.WorkflowId("unfinished")].to_payload()
    revision = turn.revision
    assert hook(root, "codex", json.dumps({**payload, "tool_use_id": "second"}), {})[0] == 0
    assert kernel.inspect(before.session.id).foreground_turns[state.session.root_actor_id].revision == revision


@pytest.mark.parametrize("invalid", ["thread", "foreign-root", "child", "stale", "completed", "unclassified", "missing-text", "later-unclassified", "later-wrong-turn"])
def test_bypass_recovery_rejects_unverified_current_user_turn(runtime, invalid):
    root, _, transcript, _ = runtime
    kernel, before, payload = skipped_prompt(runtime)
    environment = {"CODEX_THREAD_ID": "foreign" if invalid == "thread" else "root"}
    if invalid in {"foreign-root", "child"}:
        rows = [json.loads(line) for line in transcript.read_text().splitlines()]
        rows[0]["payload"]["id" if invalid == "foreign-root" else "parent_thread_id"] = "foreign"
        transcript.write_text("".join(json.dumps(row) + "\n" for row in rows))
    elif invalid == "stale":
        native_turn_started(transcript, "newer")
    elif invalid == "completed":
        with transcript.open("a") as stream:
            stream.write(json.dumps({"type": "event_msg", "payload": {"type": "task_complete", "turn_id": "current"}}) + "\n")
    elif invalid in {"later-unclassified", "later-wrong-turn"}:
        record = {"type": "response_item", "payload": {"type": "message", "role": "user",
            "content": [{"type": "input_text", "text": "Unknown later instruction"}]}}
        if invalid == "later-wrong-turn":
            record["payload"]["internal_chat_message_metadata_passthrough"] = {
                "turn_id": "different", "content_item_kinds": ["user.text"]}
        with transcript.open("a") as stream:
            stream.write(json.dumps(record) + "\n")
    elif invalid in {"unclassified", "missing-text"}:
        rows = [json.loads(line) for line in transcript.read_text().splitlines()]
        if invalid == "missing-text":
            rows.pop()
        else:
            rows[-1]["payload"]["internal_chat_message_metadata_passthrough"]["content_item_kinds"] = ["agents_md.instructions"]
        transcript.write_text("".join(json.dumps(row) + "\n" for row in rows))
    with pytest.raises(ValueError):
        hook(root, "codex", json.dumps(payload), environment)
    assert kernel.inspect(before.session.id).to_payload() == before.to_payload()

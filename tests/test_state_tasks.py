"""Named state tasks preserve native binding and kernel/claim authority."""

import pytest

from neurath.agents import mcp
from tests.test_task_tools import bound_call

pytest_plugins = ["tests.test_agent_hooks"]


def call(sessions, name, inputs=None, *, invocation=None, host="codex", session="api"):
    bound = bound_call(sessions, name, inputs or {}, invocation=invocation or name,
                       host=host, session=session)
    return mcp.call_tool(sessions[0], bound, name=name)


def test_named_state_inventory_has_closed_inputs():
    from neurath.runtime.task_schema import definitions
    tools = {item["name"]: item for item in definitions()}
    for name in ("session_inspect", "turn_inspect", "worktree_inspect", "worktree_claim",
                 "worktree_release"):
        assert name in tools
        schema = tools[name]["inputSchema"]
        assert schema["additionalProperties"] is False
        assert not {"argv", "actor", "session", "cwd", "root"} & schema["properties"].keys()


@pytest.mark.parametrize("host,session", [("codex", "api"), ("claude-code", "ui")])
def test_bound_session_turn_and_claim_without_cli(sessions, monkeypatch, host, session):
    from scripts.agent_harness.state_cli import StateCliApplication
    monkeypatch.setattr(StateCliApplication, "run", lambda *a, **k: pytest.fail("CLI gateway"))
    state = call(sessions, "session_inspect", host=host, session=session)
    turn = call(sessions, "turn_inspect", host=host, session=session)
    assert state["session"]["id"] == session
    assert turn["status"] == "active"
    assert call(sessions, "worktree_inspect", host=host, session=session)["claim"] is None
    claim = call(sessions, "worktree_claim", host=host, session=session)
    assert claim["session_id"] == session
    again = call(sessions, "worktree_claim", invocation="claim-retry", host=host, session=session)
    assert again == claim
    released = call(sessions, "worktree_release", {
        "expected_lease_epoch": claim["lease_epoch"], "fencing_token": claim["fencing_token"]},
        host=host, session=session)
    assert released["released"] is True


def test_worktree_foreign_owner_and_stale_release_are_denied(sessions):
    claim = call(sessions, "worktree_claim")
    with pytest.raises(ValueError):
        call(sessions, "worktree_claim", host="claude-code", session="ui")
    with pytest.raises(ValueError):
        call(sessions, "worktree_release", {"expected_lease_epoch": claim["lease_epoch"] + 1,
             "fencing_token": claim["fencing_token"]})
    assert call(sessions, "worktree_inspect")["claim"] == claim


def prepare_inputs(**updates):
    return {"batch_id": "batch", "kind": "local-mutation", "targets": ["result.txt"],
            "expectations": [{"observable_id": "result.txt", "expected_delta": "created"}],
            "key": "prepare", **updates}


def test_prepare_does_not_write_or_fabricate_completion(sessions):
    root, _ = sessions
    call(sessions, "worktree_claim")
    prepared = call(sessions, "material_prepare", prepare_inputs())
    assert not (root / "result.txt").exists()
    assert prepared["expectations"][0]["baseline_digest"] is None
    with pytest.raises(ValueError):
        call(sessions, "material_resolve", {"batch_id": "batch", "expected_revision": prepared["revision"],
            "resolution": "completed", "key": "fake-complete"})
    assert call(sessions, "material_read")["batch"]["status"] == "open"


@pytest.mark.parametrize("updates", [
    {"targets": ["../outside.txt"]},
    {"targets": ["result.txt", "./result.txt"]},
    {"targets": []},
    {"expectations": [{"observable_id": "other.txt", "expected_delta": "created"}]},
    {"expectations": [{"observable_id": "result.txt", "expected_delta": "created", "baseline_digest": "forged"}]},
    {"expectations": [{"observable_id": "result.txt"}]},
    {"kind": "external-mutation"},
    {"actor": "foreign"},
])
def test_prepare_rejects_path_and_input_authority_injection(sessions, updates):
    call(sessions, "worktree_claim")
    with pytest.raises(ValueError):
        call(sessions, "material_prepare", prepare_inputs(**updates))


def test_material_prepare_requires_exact_worktree_owner(sessions):
    call(sessions, "worktree_claim", host="claude-code", session="ui")
    with pytest.raises(ValueError, match="own|claim"):
        call(sessions, "material_prepare", prepare_inputs())


def test_state_binding_cannot_cross_a_new_native_turn(sessions):
    root, invoke = sessions
    assert invoke("claude-code", "no-turn", "SessionStart", source="startup")[0] == 0
    assert invoke("claude-code", "no-turn", "UserPromptSubmit", prompt="first")[0] == 0
    bound = bound_call(sessions, "worktree_claim", {}, invocation="stale", host="claude-code", session="no-turn")
    assert invoke("claude-code", "no-turn", "UserPromptSubmit", prompt="new")[0] == 0
    with pytest.raises(ValueError):
        mcp.call_tool(root, bound, name="worktree_claim")


def test_material_retry_changed_content_is_rejected(sessions):
    call(sessions, "worktree_claim")
    first = call(sessions, "material_prepare", prepare_inputs())
    retry = call(sessions, "material_prepare", prepare_inputs(), invocation="retry")
    assert retry == first
    with pytest.raises(ValueError):
        call(sessions, "material_prepare", prepare_inputs(targets=["other.txt"], expectations=[
            {"observable_id": "other.txt", "expected_delta": "created"}]), invocation="conflict")


def test_native_edits_do_not_need_or_record_material_batches(sessions):
    root, invoke = sessions
    call(sessions, "worktree_claim", host="claude-code", session="ui")
    payload = {"file_path": str(root / "result.txt"), "content": "observed"}
    assert invoke("claude-code", "ui", "PreToolUse", tool_name="Write",
                   tool_use_id="write-result", tool_input=payload)[0] == 0
    (root / "result.txt").write_text("observed")
    assert invoke("claude-code", "ui", "PostToolUse", tool_name="Write",
                   tool_use_id="write-result", tool_input=payload,
                   tool_response={"success": True})[0] == 0
    assert call(sessions, "material_read", host="claude-code", session="ui")["batch"] is None
    assert (root / "result.txt").read_text() == "observed"


def test_key_cannot_be_rebound_to_another_batch(sessions):
    call(sessions, "worktree_claim")
    initial = call(sessions, "material_prepare", prepare_inputs())
    call(sessions, "material_resolve", {"batch_id": "batch", "expected_revision": initial["revision"], "resolution": "aborted", "key": "abort"})
    with pytest.raises(ValueError, match="key.*different"):
        call(sessions, "material_prepare", prepare_inputs(batch_id="another-batch"), invocation="rebound-key")


def test_prepare_replay_preserves_original_baseline_after_file_changes(sessions):
    root, _ = sessions
    call(sessions, "worktree_claim")
    initial = call(sessions, "material_prepare", prepare_inputs())
    (root / "result.txt").write_text("later")
    retry = call(sessions, "material_prepare", prepare_inputs(), invocation="post-change-retry")
    assert retry == initial


def test_material_cannot_follow_parent_symlink_outside_worktree(sessions, tmp_path_factory):
    root, _ = sessions
    outside = tmp_path_factory.mktemp("outside")
    (root / "escape").symlink_to(outside, target_is_directory=True)
    call(sessions, "worktree_claim")
    with pytest.raises(ValueError, match="worktree"):
        call(sessions, "material_prepare", prepare_inputs(targets=["escape/new.txt"], expectations=[
            {"observable_id": "escape/new.txt", "expected_delta": "created"}]))

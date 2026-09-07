"""A created transport handle cannot grant activation, permissions or ownership."""

import json

import pytest

from neurath.providers import readiness


def stage(status="verified", reason=None):
    return {"status": status, "reason": reason, "evidence": {}}


def test_each_missing_stage_prevents_implementation_even_when_other_stages_pass():
    for key in ("installation", "activation", "policy", "ownership"):
        stages = {name: stage() for name in ("installation", "activation", "policy", "ownership")}
        stages[key] = stage("unobserved", "missing")
        assert readiness._assess(stages)["implementation_ready"] is False


def test_observation_and_approval_failures_coexist_without_becoming_generic_blocked():
    stages = {"installation": stage(), "activation": stage("failed", "registration-missing"),
              "policy": stage("unobserved", "policy-unobservable"),
              "ownership": stage("failed", "claim-conflict")}
    result = readiness._assess(stages, waiting="waiting-on-approval")
    assert result["waiting"] == "waiting-on-approval"
    assert result["stages"] == stages
    assert result["implementation_ready"] is False
    assert result["authority"] == "diagnostic"


def test_require_ready_rechecks_instead_of_accepting_a_saved_ready_object(monkeypatch):
    calls = []
    def inspect(root, *, requested_policy=None):
        calls.append(root)
        return {"implementation_ready": len(calls) == 1, "stages": {}}
    monkeypatch.setattr(readiness, "inspect_readiness", inspect)
    readiness.require_ready("/work")
    with pytest.raises(readiness.SessionNotReady):
        readiness.require_ready("/work")
    assert len(calls) == 2


@pytest.mark.parametrize("wrong", ["turn", "cwd", "missing"])
def test_policy_readback_requires_exact_current_native_turn_and_workspace(tmp_path, wrong):
    path = tmp_path / "native.jsonl"
    payload = {"turn_id": "current", "cwd": str(tmp_path), "approval_policy": "never",
               "sandbox_policy": {"type": "workspace-write", "network_access": False}}
    if wrong == "turn":
        payload["turn_id"] = "other"
    elif wrong == "cwd":
        payload["cwd"] = str(tmp_path.parent)
    else:
        del payload["sandbox_policy"]
    path.write_text(json.dumps({"type": "turn_context", "payload": payload}) + "\n")
    result = readiness._codex_policy(path, "current", tmp_path)
    assert result["status"] == "unobserved"


def test_policy_readback_reports_exact_values_without_normalizing_auto_review(tmp_path):
    path = tmp_path / "native.jsonl"
    payload = {"turn_id": "current", "cwd": str(tmp_path), "approval_policy": "on-request",
               "approvals_reviewer": "auto_review", "sandbox_policy": {"type": "danger-full-access"}}
    path.write_text(json.dumps({"type": "turn_context", "payload": payload}) + "\n")
    result = readiness._codex_policy(path, "current", tmp_path)
    assert result["status"] == "verified"
    assert result["evidence"]["approval_policy"] == "on-request"
    assert result["evidence"]["approvals_reviewer"] == "auto_review"
    assert result["evidence"]["sandbox_policy"] == {"type": "danger-full-access"}


def test_native_claude_policy_requires_current_invocation_binding():
    from neurath.agents.store import AgentIdentity
    identity = AgentIdentity("claude-code", "session", "actor")
    evidence = {"host": "claude-code", "session": "session", "actor": "actor",
                "turn": "turn", "tool_use_id": "tool-1", "permission_mode": "default"}
    observed = readiness._claude_policy(evidence, identity, "turn")
    assert observed["status"] == "verified"
    assert observed["evidence"]["sandbox_observation"] == "unobserved"
    for field in ("session", "actor", "turn", "host", "tool_use_id", "permission_mode"):
        bad = {**evidence, field: ""}
        assert readiness._claude_policy(bad, identity, "turn")["status"] == "failed"
    assert readiness._claude_policy(None, identity, "turn")["status"] == "unobserved"


@pytest.mark.parametrize("policy", [
    {"permission_mode": "plan"}, {"sandbox_policy": {"type": "read-only"}},
    {"sandbox_policy": {"type": "danger-full-access"}, "collaboration_mode": "plan"},
])
def test_observed_plan_or_read_only_mode_is_not_implementation_permission(policy):
    stages = {name: stage() for name in ("installation", "activation", "policy", "ownership")}
    stages["policy"]["evidence"] = policy
    report = readiness._assess(stages)
    assert report["observation_ready"] is True
    assert report["implementation_ready"] is False


def test_new_claude_prompt_invalidates_same_generation_binding():
    from types import SimpleNamespace
    turn = SimpleNamespace(generation=1, vendor_turn_id=None,
        user_prompt_receipt=SimpleNamespace(turn_revision=2, prompt_digest="new"))
    evidence = {"user_prompt_receipt": {"turn_revision": 1, "prompt_digest": "old"}}
    assert readiness._prompt_matches(evidence, turn) is False
    assert readiness._prompt_matches({}, turn) is False
    evidence["user_prompt_receipt"] = {"turn_revision": 2, "prompt_digest": "new"}
    assert readiness._prompt_matches(evidence, turn) is True

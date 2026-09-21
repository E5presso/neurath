"""Planning rejects unrepresentable inheritance before storing a ready plan."""
import copy
import subprocess

import pytest

from neurath.agents.store import AgentIdentity
from neurath.runtime import model_tasks
from tests.test_provider_policy_bridge import evidence, observation


@pytest.fixture
def planning(tmp_path, monkeypatch):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    saved = []
    policy = evidence(tmp_path)
    policy["target_configuration_observation"] = observation(tmp_path, "claude-code")
    monkeypatch.setattr("neurath.runtime.tasks._verification_owner", lambda *a: (1, "turn"))
    monkeypatch.setattr(model_tasks, "observed_policy", lambda *a: policy)
    monkeypatch.setattr(model_tasks, "store_for", lambda *a: object())
    monkeypatch.setattr(model_tasks, "refresh_inventory", lambda *a, **k: pytest.fail("plan launched a model observation"))
    def prepare(store, identity, fields, observed):
        saved.append(copy.deepcopy(fields))
        return {"status": "ready"}
    monkeypatch.setattr(model_tasks, "prepare_plan", prepare)
    def run(execution=None, provider="claude-code"):
        return model_tasks.run(tmp_path, "provider_plan", {
            "provider": provider, "worktree": str(tmp_path),
            "execution": execution or {"mode": "inherit"}},
            identity=AgentIdentity("codex", "root", "owner"), expected_turn="turn")
    return tmp_path, policy, saved, run


@pytest.mark.parametrize("settings,dimension", [
    ({"permissions": {"deny": ["Bash"]}}, "tool_denylist"),
    ({"permissions": {"allow": ["Read"]}}, "tool_allowlist"),
    ({"hooks": {"PreToolUse": [{"hooks": [{"type": "command", "command": "custom-hook"}]}]}}, "hooks"),
])
def test_plan_rejects_unmappable_controls_before_persistence(planning, settings, dimension):
    root, policy, saved, run = planning
    policy["target_configuration_observation"] = observation(root, "claude-code", settings)
    with pytest.raises(ValueError, match=dimension):
        run()
    assert saved == []


def test_plan_rejects_nested_policy_override(planning):
    _, _, saved, run = planning
    with pytest.raises(ValueError, match="requested:permission_mode"):
        run({"mode": "inherit", "permission_mode": "auto"})
    assert saved == []


def test_plan_rejects_codex_sandbox_unsupported_by_dispatch(planning):
    root, policy, saved, run = planning
    policy["sandbox_policy"] = {"type": "external-sandbox"}
    policy["target_configuration_observation"] = observation(root, "codex")
    with pytest.raises(ValueError, match="sandbox_policy"):
        run(provider="codex")
    assert saved == []


def test_supported_plan_keeps_execution_inputs_and_policy(planning):
    _, policy, saved, run = planning
    before = copy.deepcopy(policy)
    assert run() == {"status": "ready"}
    assert saved[0]["execution"] == {"mode": "inherit"}
    assert policy == before


def test_explicit_target_native_does_not_use_inherit_gate(planning, monkeypatch):
    root, policy, saved, run = planning
    policy["target_configuration_observation"] = observation(root, "claude-code", {"permissions": {"deny": ["Bash"]}})
    monkeypatch.setattr("neurath.runtime.provider_policy.target_native_settings", lambda *a: {"permission_mode": "auto"})
    assert run({"mode": "target-native"}) == {"status": "ready"}
    assert saved[0]["execution"] == {"mode": "target-native"}

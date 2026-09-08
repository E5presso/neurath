import copy

import pytest

from neurath.agents.store import AgentIdentity
from neurath.runtime.provider_policy import COVERAGE, PolicyObservationError, controls, planning_policy, resolve_policy

BROAD = {"sandbox_policy": {"type": "danger-full-access"}, "approval_policy": "never",
         "collaboration_mode": "default", "approvals_reviewer": None}


def observation(root, provider="codex", settings=None, **extra):
    return {"status": "verified", "provider": provider, "root": str(root.resolve()),
            "source": "test-native-bound-configuration", "coverage": sorted(COVERAGE),
            "effective_settings": settings or {}, "rules": [],
            "filesystem": "unrestricted", "network": "unrestricted", **extra}


def evidence(root, provider="codex", settings=None, **extra):
    return {**(BROAD if provider == "codex" else {"permission_mode": "dontAsk"}),
            "configuration_observation": observation(root, provider, settings), **extra}


def fields(root, provider="codex", mode="inherit"):
    return {"provider": provider, "mode": mode, "worktree": str(root)}


def test_actual_mode_preserved_and_target_denies_are_not_silent(tmp_path):
    policy = evidence(tmp_path)
    result = resolve_policy(tmp_path, AgentIdentity("codex", "root", "actor"), fields(tmp_path), policy)
    assert result["mode"] == "danger-full-access"
    assert result["approval_policy"] == "never"
    policy["target_configuration_observation"] = observation(tmp_path, "claude-code", {"permissions": {"deny": ["Bash"]}})
    with pytest.raises(ValueError, match="tool_denylist"):
        resolve_policy(tmp_path, AgentIdentity("codex", "root", "actor"), fields(tmp_path, "claude-code"), policy)


def test_explicit_type_matches_full_inherited_sandbox(tmp_path):
    policy = evidence(tmp_path, sandbox_policy={"type": "workspace-write", "writable_roots": ["/shared"], "network_access": False})
    result = resolve_policy(tmp_path, AgentIdentity("codex", "root", "actor"), fields(tmp_path, mode="workspace-write"), policy)
    assert result["inherited_sandbox"] == policy["sandbox_policy"]
    with pytest.raises(ValueError, match="requested:sandbox_policy.type"):
        resolve_policy(tmp_path, AgentIdentity("codex", "root", "actor"), fields(tmp_path, mode="read-only"), policy)


def test_claude_dontask_never_becomes_bypass(tmp_path):
    result = resolve_policy(tmp_path, AgentIdentity("claude-code", "root", "actor"), fields(tmp_path, "claude-code"), evidence(tmp_path, "claude-code"))
    assert result["permission_mode"] == "dontAsk"


def test_disk_configuration_is_not_loaded_evidence(tmp_path):
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude/settings.json").write_text('{"permissions":{"deny":["Bash"]}}')
    # Configured files are conservative observations, never loaded-state proof.
    configured = controls(tmp_path, "claude-code", {"permission_mode": "bypassPermissions"})
    assert configured["tool_denylist"] == ["Bash"]
    assert configured["filesystem"] == "unobserved"
    # A precise native observation overrides candidate files (e.g. sources=[]).
    assert controls(tmp_path, "claude-code", evidence(tmp_path, "claude-code"))["tool_denylist"] == []


@pytest.mark.parametrize("scope", sorted(COVERAGE))
def test_missing_managed_or_override_coverage_blocks(tmp_path, scope):
    policy = evidence(tmp_path)
    policy["configuration_observation"]["coverage"].remove(scope)
    with pytest.raises(PolicyObservationError, match=scope):
        controls(tmp_path, "codex", policy)


@pytest.mark.parametrize("settings", [
    {"permissions": {"ask": ["Bash(curl *)"]}},
    {"permissions": {"additionalDirectories": ["/extra"]}},
    {"sandbox": {"enabled": True, "filesystem": {"denyRead": ["/private"]}}},
    {"sandbox": {"enabled": True, "network": {"allowedDomains": ["example.com"]}}},
])
def test_claude_native_details_are_not_erased(tmp_path, settings):
    base = evidence(tmp_path, "claude-code")
    source = evidence(tmp_path, "claude-code", settings)
    assert controls(tmp_path, "claude-code", base) != controls(tmp_path, "claude-code", source)
    source["target_configuration_observation"] = base["configuration_observation"]
    with pytest.raises(ValueError, match="target:tool_denylist"):
        resolve_policy(tmp_path, AgentIdentity("claude-code", "root", "actor"), fields(tmp_path, "claude-code"), source)


@pytest.mark.parametrize("decision,field", [("allow", "tool_allowlist"), ("prompt", "tool_denylist"), ("forbidden", "tool_denylist")])
def test_all_codex_rule_decisions_are_preserved(tmp_path, decision, field):
    policy = evidence(tmp_path)
    policy["configuration_observation"]["rules"] = [{"decision": decision, "pattern": ["git", "status"]}]
    assert controls(tmp_path, "codex", policy)[field]
    policy["target_configuration_observation"] = observation(tmp_path)
    with pytest.raises(ValueError, match="target:" + field):
        resolve_policy(tmp_path, AgentIdentity("codex", "root", "actor"), fields(tmp_path), policy)


def test_complete_hook_contract_required_and_options_preserved(tmp_path, monkeypatch):
    from neurath.install.projection import host_hooks
    monkeypatch.setattr("neurath.install.transaction.read_state", lambda _: {"distribution": "same-distribution"})
    native_hooks = host_hooks(tmp_path, "codex")
    complete = evidence(tmp_path, settings={"hooks": native_hooks})
    expected = controls(tmp_path, "codex", complete)["hooks"]
    assert expected == ["neurath:same-distribution"]
    variants = []
    missing = copy.deepcopy(native_hooks)
    missing.pop("PreToolUse")
    variants.append({"hooks": missing})
    matcher = copy.deepcopy(native_hooks)
    matcher["PreToolUse"][0]["matcher"] = "Read"
    variants.append({"hooks": matcher})
    timeout = copy.deepcopy(native_hooks)
    timeout["PreToolUse"][0]["hooks"][0]["timeout"] = 1
    variants.append({"hooks": timeout})
    variants.append({"hooks": native_hooks, "disableAllHooks": True})
    for settings in variants:
        assert controls(tmp_path, "codex", evidence(tmp_path, settings=settings))["hooks"] != expected
    # Provider-specific complete expected event sets map only after both are checked.
    claude = evidence(tmp_path, "claude-code", {"hooks": host_hooks(tmp_path, "claude-code")})
    assert controls(tmp_path, "claude-code", claude)["hooks"] == expected


def test_target_preparation_is_separate_from_source_loaded_evidence(tmp_path):
    policy = evidence(tmp_path)
    policy["configuration_observation"]["status"] = "prepared"
    with pytest.raises(PolicyObservationError):
        controls(tmp_path, "codex", policy)
    policy = evidence(tmp_path)
    target = tmp_path / "target"
    policy["target_configuration_observation"] = observation(target, status="prepared")
    plan = planning_policy(tmp_path, AgentIdentity("codex", "root", "actor"), fields(target), policy)
    assert plan["native_fields"] == BROAD
    assert plan["target_observation_status"] == "prepared"
    assert "settings" not in plan  # not an application/readiness result
    policy["target_configuration_observation"]["root"] = str(tmp_path)
    with pytest.raises(PolicyObservationError, match="target.configuration_binding"):
        planning_policy(tmp_path, AgentIdentity("codex", "root", "actor"), fields(target), policy)

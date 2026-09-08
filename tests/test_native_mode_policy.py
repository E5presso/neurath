import pytest
from neurath.agents.store import AgentIdentity
from neurath.runtime.provider_policy import controls, planning_policy, resolve_policy

COD = {"approval_policy": "never", "sandbox_policy": {"type": "danger-full-access"}, "collaboration_mode": "default"}

@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.delenv("CODEX_HOME", raising=False)


def resolve(root, source, target, evidence):
    return resolve_policy(root, AgentIdentity(source, "root", "actor"),
        {"provider": target, "worktree": str(root), "mode": "inherit"}, evidence)


@pytest.mark.parametrize("mode", ["dontAsk", "default", "plan", "acceptEdits", "auto", "bypassPermissions"])
def test_same_claude_native_mode_needs_no_global_os_proof(tmp_path, mode):
    result = resolve(tmp_path, "claude-code", "claude-code", {"permission_mode": mode})
    assert result["permission_mode"] == mode
    proof = result["policy_inheritance"]
    assert proof["controls"]["filesystem"] == proof["controls"]["network"] == "unobserved"
    assert proof["host_confinement"]["status"] == "unobserved"
    assert proof["source_observation_status"] == "configured"


def test_same_codex_keeps_exact_workspace_policy(tmp_path):
    policy = {**COD, "sandbox_policy": {"type": "workspace-write", "writable_roots": ["/shared"], "network_access": False}}
    assert resolve(tmp_path, "codex", "codex", policy)["inherited_sandbox"] == policy["sandbox_policy"]


@pytest.mark.parametrize("source,target,policy", [("codex", "claude-code", COD), ("claude-code", "codex", {"permission_mode": "bypassPermissions"})])
def test_cross_broad_mode_does_not_assert_global_os_unrestricted(tmp_path, source, target, policy):
    result = resolve(tmp_path, source, target, policy)
    assert result["policy_inheritance"]["host_confinement"] == {"status": "unobserved", "scope": "ambient-os"}
    if source == "claude-code":
        assert result["policy_inheritance"]["controls"]["filesystem"] == "unobserved"


def test_explicit_configured_claude_restrictions_do_not_disappear(tmp_path):
    config = tmp_path / ".claude"
    config.mkdir()
    (config / "settings.json").write_text('{"permissions":{"ask":["Bash(curl *)"],"additionalDirectories":["/shared"]}}')
    value = controls(tmp_path, "claude-code", {"permission_mode": "bypassPermissions"})
    assert value["tool_denylist"]
    assert resolve(tmp_path, "claude-code", "claude-code", {"permission_mode": "bypassPermissions"})["permission_mode"] == "bypassPermissions"
    with pytest.raises(ValueError, match="tool_denylist"):
        resolve(tmp_path, "claude-code", "codex", {"permission_mode": "bypassPermissions"})


def test_codex_allow_rule_remains_known_during_ordinary_inheritance(tmp_path):
    rules = tmp_path / ".codex/rules"
    rules.mkdir(parents=True)
    (rules / "default.rules").write_text('prefix_rule(pattern=["git", "status"], decision="allow")')
    assert controls(tmp_path, "codex", COD)["tool_allowlist"]
    with pytest.raises(ValueError, match="tool_allowlist"):
        resolve(tmp_path, "codex", "claude-code", COD)


def test_unrelated_model_and_ui_settings_do_not_block(tmp_path):
    config = tmp_path / ".codex"
    config.mkdir()
    (config / "config.toml").write_text('model="configured-model"\n[tools.web_search]\ncontext_size="high"\n')
    assert resolve(tmp_path, "codex", "claude-code", COD)["permission_mode"] == "bypassPermissions"


def test_known_native_restriction_still_blocks_cross_mapping(tmp_path):
    with pytest.raises(ValueError, match="sandbox_policy"):
        resolve(tmp_path, "codex", "claude-code", {**COD, "sandbox_policy": {"type": "workspace-write"}})


def test_inherited_host_boundary_is_metadata_not_a_native_field(tmp_path):
    proof = {"status": "inherited-host", "source": "owned-subprocess-parent-boundary"}
    result = resolve(tmp_path, "claude-code", "codex", {"permission_mode": "bypassPermissions", "host_confinement": proof})
    assert result["policy_inheritance"]["host_confinement"] == proof


def test_codex_trust_hash_table_is_not_an_event_handler_array(tmp_path):
    config = tmp_path / ".codex"
    config.mkdir()
    (config / "config.toml").write_text('[hooks.state.fixture]\ntrusted_hash="known"\n')
    value = resolve(tmp_path, "codex", "codex", COD)
    assert value["mode"] == "danger-full-access"
    assert value["policy_inheritance"]["controls"]["tool_denylist"] == []

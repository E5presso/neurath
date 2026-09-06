"""Global collaboration installation preserves existing MCP servers and permissions."""

import json
import subprocess
import tomllib

import pytest

from neurath.install.transaction import InstallError, apply_plan, make_plan


def test_mcp_install_update_uninstall_preserves_user_configuration(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    codex = tmp_path / ".codex/config.toml"
    codex.parent.mkdir()
    original = '# keep comment\nmodel = "chosen"\n[mcp_servers.other]\ncommand = "other"\n'
    codex.write_text(original)
    claude = tmp_path / ".mcp.json"
    claude_original = {"mcpServers": {"other": {"command": "other"}}}
    claude.write_text(json.dumps(claude_original))
    settings = tmp_path / ".claude/settings.json"
    settings.parent.mkdir()
    permissions = {"allow": ["Read"], "deny": ["Bash(rm *)"]}
    settings.write_text(json.dumps({"permissions": permissions}))
    apply_plan(tmp_path, make_plan(tmp_path))
    assert tomllib.loads(codex.read_text())["mcp_servers"]["neurath_collaboration"]["command"]
    assert tomllib.loads(codex.read_text())["mcp_servers"]["neurath_collaboration"]["tools"]["agent"]["approval_mode"] == "approve"
    assert "# keep comment" in codex.read_text()
    assert json.loads(claude.read_text())["mcpServers"]["other"] == {"command": "other"}
    assert json.loads(claude.read_text())["mcpServers"]["neurath_collaboration"]["command"]
    assert json.loads(settings.read_text())["permissions"] == permissions
    assert not make_plan(tmp_path, action="update")["changes"]
    apply_plan(tmp_path, make_plan(tmp_path, action="uninstall"))
    assert codex.read_text() == original
    assert json.loads(claude.read_text()) == claude_original


@pytest.mark.parametrize("host", ["codex", "claude-code"])
def test_existing_neurath_mcp_name_is_a_conflict_not_overwritten(tmp_path, host):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    if host == "codex":
        path = tmp_path / ".codex/config.toml"
        path.parent.mkdir()
        path.write_text('[mcp_servers.neurath_collaboration]\ncommand = "custom"\n')
    else:
        path = tmp_path / ".mcp.json"
        path.write_text(json.dumps({"mcpServers": {"neurath_collaboration": {"command": "custom"}}}))
    before = path.read_bytes()
    with pytest.raises(InstallError, match="conflict"):
        make_plan(tmp_path, hosts=[host])
    assert path.read_bytes() == before


def test_readonly_claude_gets_only_the_project_communication_server(tmp_path, monkeypatch):
    from neurath.agents.runner import command

    monkeypatch.setattr("shutil.which", lambda name: "/bin/claude")
    args = command("claude-code", "selected-model", root=tmp_path)
    assert args[args.index("--tools") + 1] == "Read,Grep,Glob"
    assert args[args.index("--allowedTools") + 1] == "Read,Grep,Glob,mcp__neurath_collaboration__agent"
    config = json.loads(args[args.index("--mcp-config") + 1])
    assert list(config["mcpServers"]) == ["neurath_collaboration"]
    assert config["mcpServers"]["neurath_collaboration"]["args"][-1] == str(tmp_path)


def test_unicode_project_path_roundtrips_through_both_native_configs(tmp_path):
    root = tmp_path / "newsroom-📰"
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    apply_plan(root, make_plan(root))
    codex = tomllib.loads((root / ".codex/config.toml").read_text())["mcp_servers"]["neurath_collaboration"]
    claude = json.loads((root / ".mcp.json").read_text())["mcpServers"]["neurath_collaboration"]
    assert codex["args"][-1] == claude["args"][-1] == str(root)

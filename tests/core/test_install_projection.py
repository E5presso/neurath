"""New installs bind both hosts to the core without changing host permissions."""

import json
import subprocess
import tomllib

from neurath.install.desired import InstallationProjection
from neurath.install.file_values import bytes_of, file_value
from neurath.install.projection import asset_files, host_hooks


def test_each_host_gets_its_own_core_adapter_and_keeps_user_permissions(tmp_path):
    original = {
        ".codex/config.toml": file_value(
            b'approval_policy = "on-request"\nsandbox_mode = "read-only"\n'
        ),
        ".mcp.json": file_value(
            json.dumps({"mcpServers": {"user_server": {"command": "user"}}}).encode()
        ),
    }
    projection = InstallationProjection(tmp_path, {}, original.get)
    projection._mcp_settings(["codex", "claude-code"])
    codex = tomllib.loads(bytes_of(projection.desired[".codex/config.toml"]).decode())
    claude = json.loads(bytes_of(projection.desired[".mcp.json"]))
    assert codex["approval_policy"] == "on-request" and codex["sandbox_mode"] == "read-only"
    assert claude["mcpServers"]["user_server"] == {"command": "user"}
    for provider, server in [
        ("codex", codex["mcp_servers"]["neurath_collaboration"]),
        ("claude-code", claude["mcpServers"]["neurath_collaboration"]),
    ]:
        assert "--provider" in server["args"]
        assert server["args"][server["args"].index("--provider") + 1] == provider
        assert "tools" not in server  # No generated per-tool approval override.
        assert "agent" not in server.get("enabled_tools", [])


def test_hook_callback_does_not_depend_on_active_cwd_or_worktree_launcher(tmp_path):
    root = tmp_path / "project with spaces"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    for provider in ("codex", "claude-code"):
        command = host_hooks(root, provider)["SessionStart"][0]["hooks"][0]["command"]
        payload = json.dumps({"hook_event_name": "SessionStart", "session_id": "fixture"})
        result = subprocess.run(
            command,
            shell=True,
            check=False,
            cwd=tmp_path,
            input=payload,
            text=True,
            capture_output=True,
        )
        assert result.returncode == 0, result.stderr
        assert isinstance(json.loads(result.stdout), dict)


def test_installed_launcher_and_skill_contract_use_new_core_only():
    files = asset_files("generic", ["codex", "claude-code"])
    launcher = files[".neurath/run"][0].decode()
    assert "neurath.core.mcp" in launcher
    assert "neurath.agents.mcp" not in launcher
    profile = json.loads(files[".neurath/profile.json"][0])
    assert profile["contracts"] == "bundle:.agents/skills/core-skills.json"
    assert ".neurath/reference/core-skills.json" in files

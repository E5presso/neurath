"""Installer behavior specified before implementation."""

import json
import subprocess
import sys

import pytest

from neurath.install.transaction import InstallError, apply_plan, make_plan, read_state


@pytest.fixture
def repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    return tmp_path


def test_codex_mcp_timeout_exceeds_supported_verifier_deadline(repo):
    import tomllib
    apply_plan(repo, make_plan(repo))
    config = tomllib.loads((repo / '.codex/config.toml').read_text())
    assert config['mcp_servers']['neurath_collaboration'].get('tool_timeout_sec', 0) > 3600
    assert 'tool_timeout_sec' not in json.loads((repo / '.mcp.json').read_text())['mcpServers']['neurath_collaboration']


def test_both_hosts_preserve_user_files_and_reinstall_is_noop(repo):
    original = "# My own rules\nDo useful work.\n"
    (repo / "AGENTS.md").write_text(original)
    (repo / "CLAUDE.md").write_text("Keep this Claude instruction.\n")
    (repo / ".claude").mkdir()
    settings = {
        "permissions": {"deny": ["Bash(rm *)"]},
        "model": "user-choice",
        "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo existing"}]}]},
    }
    (repo / ".claude/settings.json").write_text(json.dumps(settings))
    pyproject = '[project]\nname="existing"\nversion="1"\n'
    package = '{"name":"existing"}'
    (repo / "pyproject.toml").write_text(pyproject)
    (repo / "package.json").write_text(package)
    plan = make_plan(repo)
    assert plan["changes"]
    apply_plan(repo, plan)
    assert (repo / "AGENTS.md").read_text().startswith(original)
    installed = json.loads((repo / ".claude/settings.json").read_text())
    assert installed["permissions"] == settings["permissions"]
    assert installed["model"] == "user-choice"
    assert installed["hooks"]["Stop"][0] == settings["hooks"]["Stop"][0]
    assert (repo / "pyproject.toml").read_text() == pyproject
    assert (repo / "package.json").read_text() == package
    assert (repo / ".claude/skills/debug").resolve() == (
        repo / ".agents/skills/debug"
    ).resolve()
    assert not (repo / ".venv").exists()
    assert make_plan(repo)["changes"] == []
    assert read_state(repo)["profile"] == "generic"


@pytest.mark.parametrize("name", [".codex/hooks.json", ".claude/settings.json", ".mcp.json"])
def test_portable_marker_removal_preserves_existing_installation_config(repo, name):
    from pathlib import Path
    from neurath.install.transaction import _migrate_checkout_bootstrap, file_value

    current = file_value((Path(__file__).resolve().parents[1] / name).read_bytes())
    legacy = json.loads((Path(__file__).resolve().parents[1] / name).read_text())
    legacy["_neurath_checkout_bootstrap"] = True
    record = {"original": None, "installed": file_value(json.dumps(legacy).encode())}
    assert _migrate_checkout_bootstrap(repo, name, record, current) == {
        "original": current, "installed": current,
    }


def test_stale_plan_refused_without_partial_mutation(repo):
    plan = make_plan(repo)
    (repo / "AGENTS.md").write_text("edited after planning")
    with pytest.raises(InstallError, match="stale"):
        apply_plan(repo, plan)
    assert not (repo / ".codex/hooks.json").exists()


@pytest.mark.parametrize("runtime_path", [
    ".monitor-pr/monitor-state.json",
    ".agents/worktrees/feature/example/file.py",
    ".agents/resources/worktrees/example.json.lock",
    ".agents/resources/worktrees/example.admission.lock",
    ".neurath/local/resources/worktrees/example.json.lock",
])
def test_runtime_is_ignored_without_changing_user_ignore(repo, runtime_path):
    original = "# user ignores\nmy-cache/\n"
    (repo / ".gitignore").write_text(original)
    apply_plan(repo, make_plan(repo))
    assert (repo / ".gitignore").read_text().startswith(original)
    probe = subprocess.run(["git", "check-ignore", "--no-index", runtime_path],
                           cwd=repo, capture_output=True, text=True)
    assert probe.returncode == 0


def test_conflicting_owned_skill_refused(repo):
    p = repo / ".agents/skills/debug"
    p.mkdir(parents=True)
    (p / "SKILL.md").write_text("user asset")
    with pytest.raises(InstallError, match="conflict"):
        make_plan(repo)
    assert not (repo / ".neurath/install.json").exists()


def test_symlink_escape_refused(repo, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside")
    (repo / ".agents").symlink_to(outside, target_is_directory=True)
    with pytest.raises(InstallError, match="symlink|escape"):
        make_plan(repo)
    assert list(outside.iterdir()) == []


def test_plan_tampering_and_wrong_target_refused(repo, tmp_path_factory):
    plan = make_plan(repo)
    plan["changes"][0]["path"] = "../escape"
    with pytest.raises(InstallError):
        apply_plan(repo, plan)
    other = tmp_path_factory.mktemp("other")
    subprocess.run(["git", "init", "-q", str(other)], check=True)
    with pytest.raises(InstallError):
        apply_plan(other, make_plan(repo))


def test_uninstall_restores_exact_bytes_and_keeps_unrelated_changes(repo):
    original = b"# original\r\n"
    (repo / "AGENTS.md").write_bytes(original)
    apply_plan(repo, make_plan(repo))
    (repo / "user-file.txt").write_text("keep")
    apply_plan(repo, make_plan(repo, action="uninstall"))
    assert (repo / "AGENTS.md").read_bytes() == original
    assert (repo / "user-file.txt").read_text() == "keep"
    assert not (repo / ".codex/hooks.json").exists()
    assert read_state(repo) is None


def test_modified_managed_file_blocks_update_and_uninstall(repo):
    apply_plan(repo, make_plan(repo))
    (repo / ".agents/skills/debug/SKILL.md").write_text("locally modified")
    for action in ("update", "uninstall"):
        with pytest.raises(InstallError, match="modified|conflict"):
            make_plan(repo, action=action)


def test_codex_update_preserves_settings_added_after_install_and_uninstall(repo, monkeypatch):
    import tomllib

    monkeypatch.setenv("CODEX_HOME", str(repo / "absent-user-config"))
    apply_plan(repo, make_plan(repo))
    path = repo / ".codex/config.toml"
    managed = path.read_text().replace(" = ", "=")
    user = '# Keep my model settings\nmodel_verbosity="low"\n'
    extra = '\n[agents]\nmax_threads=4\n[mcp_servers.external]\ncommand="existing-server"\n'
    path.write_text(user + managed + extra)
    expected = tomllib.loads(user + extra)
    apply_plan(repo, make_plan(repo, action="update"))
    current = tomllib.loads(path.read_text())
    current["mcp_servers"].pop("neurath_collaboration")
    assert current.pop("tools") == {"update_plan": {"enabled": True}}
    assert current == expected
    assert "# Keep my model settings" in path.read_text()
    apply_plan(repo, make_plan(repo, action="uninstall"))
    assert tomllib.loads(path.read_text()) == expected
    assert extra in path.read_text()


def test_codex_managed_permission_change_is_still_a_conflict(repo):
    apply_plan(repo, make_plan(repo))
    path = repo / ".codex/config.toml"
    path.write_text(path.read_text().replace('approval_mode = "approve"', 'approval_mode = "deny"', 1))
    with pytest.raises(InstallError, match="conflict"):
        make_plan(repo, action="update")


def test_host_selection_update_and_restore(repo):
    apply_plan(repo, make_plan(repo))
    receipt = apply_plan(repo, make_plan(repo, action="update", hosts=["codex"]))
    assert read_state(repo)["hosts"] == ["codex"]
    apply_plan(repo, make_plan(repo, action="restore", receipt=receipt["id"]))
    assert read_state(repo)["profile"] == "generic"
    assert read_state(repo)["hosts"] == ["claude-code", "codex"]
    assert make_plan(repo)["changes"] == []


def test_user_project_bindings_survive_update_and_uninstall(repo):
    apply_plan(repo, make_plan(repo))
    bindings = '{"schema":1,"documents":{"intent":"SPEC.md"},"verification":{}}\n'
    (repo / ".neurath/project.json").write_text(bindings)
    apply_plan(repo, make_plan(repo, action="update"))
    assert (repo / ".neurath/project.json").read_text() == bindings
    apply_plan(repo, make_plan(repo, action="uninstall"))
    assert (repo / ".neurath/project.json").read_text() == bindings


def test_existing_shared_symlinks_and_inline_codex_config_preserved(repo):
    (repo / "AGENTS.md").write_text("# Shared rules\n")
    (repo / "CLAUDE.md").symlink_to("AGENTS.md")
    (repo / ".agents/skills").mkdir(parents=True)
    (repo / ".claude").mkdir()
    (repo / ".claude/skills").symlink_to("../.agents/skills")
    (repo / ".codex").mkdir()
    config = (
        '[hooks]\n[[hooks.Stop]]\n[[hooks.Stop.hooks]]\ntype="command"\ncommand="echo original"\n'
    )
    (repo / ".codex/config.toml").write_text(config)
    apply_plan(repo, make_plan(repo))
    import tomllib

    installed = (repo / ".codex/config.toml").read_text()
    assert installed.startswith(config)
    assert tomllib.loads(installed)["hooks"] == tomllib.loads(config)["hooks"]
    assert (repo / "CLAUDE.md").is_symlink()
    assert make_plan(repo)["changes"] == []


def test_transaction_rolls_back_and_interrupted_journal_recovers(repo, monkeypatch):
    from neurath.install import transaction as installer

    plan = make_plan(repo)
    real = installer._write
    calls = 0

    def failing_write(root, path, value):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError("injected disk failure")
        return real(root, path, value)

    monkeypatch.setattr(installer, "_write", failing_write)
    with pytest.raises(OSError):
        apply_plan(repo, plan)
    assert not (repo / "AGENTS.md").exists()
    assert read_state(repo) is None
    monkeypatch.setattr(installer, "_write", real)
    plan = make_plan(repo)
    from neurath.install.state_store import InstallStateStore
    InstallStateStore(repo, create=True).begin(plan)
    real(repo, plan["changes"][0]["path"], plan["changes"][0]["after"])
    with pytest.raises(InstallError, match="interrupted"):
        apply_plan(repo, make_plan(repo))
    assert installer.recover(repo)["recovered"]
    assert not (repo / "AGENTS.md").exists()


def test_wizard_plan_only_and_single_host_use_the_same_apply_engine(repo):
    plan_file = repo / "wizard-plan.json"
    command = [sys.executable, "-I", "-m", "neurath", "--root", str(repo)]
    process = subprocess.run(
        [*command, "wizard", "--output", str(plan_file)],
        input="generic\ncodex\nn\n",
        text=True,
        capture_output=True,
        check=False,
    )
    assert process.returncode == 0, process.stderr
    assert read_state(repo) is None
    plan = json.loads(plan_file.read_text())
    assert plan["hosts"] == ["codex"]
    assert plan == make_plan(repo, hosts=["codex"])
    process = subprocess.run(
        [*command, "apply", str(plan_file)], text=True, capture_output=True, check=False
    )
    assert process.returncode == 0, process.stderr
    assert (repo / ".codex/hooks.json").is_file()
    assert not (repo / "CLAUDE.md").exists()


def test_real_sigkill_after_partial_install_recovers_exact_original_files(repo):
    import signal

    from neurath.install import transaction as installer

    (repo / "AGENTS.md").write_text("Original project rules\n")
    script = """
import os, signal, sys
from pathlib import Path
from neurath.install import transaction as installer
root=Path(sys.argv[1])
original=installer._write
calls=0
def killed_write(root,path,value):
    global calls
    original(root,path,value)
    calls+=1
    if calls==3: os.kill(os.getpid(),signal.SIGKILL)
installer._write=killed_write
installer.apply_plan(root,installer.make_plan(root))
"""
    process = subprocess.run(
        [sys.executable, "-I", "-c", script, str(repo)], capture_output=True, check=False
    )
    assert process.returncode == -signal.SIGKILL
    from neurath.install.state_store import InstallStateStore
    assert InstallStateStore(repo).journal() is not None
    assert installer.recover(repo)["recovered"]
    assert (repo / "AGENTS.md").read_text() == "Original project rules\n"
    assert installer.read_state(repo) is None
    assert InstallStateStore(repo).journal() is None
    apply_plan(repo, make_plan(repo))
    assert make_plan(repo)["changes"] == []


def test_fresh_clone_preserves_exact_managed_instructions(repo):
    """A public checkout keeps instructions, but not private install receipts."""
    apply_plan(repo, make_plan(repo))
    published = {name: (repo / name).read_bytes() for name in ("AGENTS.md", ".gitignore")}
    apply_plan(repo, make_plan(repo, action="uninstall"))
    for name, data in published.items():
        (repo / name).write_bytes(data)
    apply_plan(repo, make_plan(repo))
    for name, data in published.items():
        assert (repo / name).read_bytes() == data
    assert not make_plan(repo)["changes"]
    apply_plan(repo, make_plan(repo, action="uninstall"))
    for name, data in published.items():
        assert (repo / name).read_bytes() == data


def test_fresh_clone_rejects_edited_managed_instructions(repo):
    apply_plan(repo, make_plan(repo))
    content = (repo / "AGENTS.md").read_text().replace("Read `.neurath/policy.md`", "Ignore `.neurath/policy.md`")
    apply_plan(repo, make_plan(repo, action="uninstall"))
    (repo / "AGENTS.md").write_text(content)
    with pytest.raises(InstallError, match="unowned managed block conflict"):
        make_plan(repo)
    assert (repo / "AGENTS.md").read_text() == content


@pytest.mark.parametrize("prefix", ["", "neurath-"])
def test_agents_guidance_routes_work_and_preserves_other_integrations(repo, prefix):
    original = "# Project instructions\nKeep these rules.\n<!-- context7 -->\nUse Context7 for library docs.\n<!-- context7 -->\n"
    (repo / "AGENTS.md").write_text(original)
    apply_plan(repo, make_plan(repo, skill_prefix=prefix))
    content = (repo / "AGENTS.md").read_text()
    assert content.startswith(original)
    for tool in ("session_status", "task_define", "task_start", "task_resolve",
                 "memory_recall", "memory_checkpoint", "memory_pull",
                 "collaboration_discover", "collaboration_inbox", "collaboration_reply",
                 "newsroom_headlines", "newsroom_read", "newsroom_publish",
                 "provider_models", "provider_plan", "provider_run", "learning_pending"):
        assert f"`{tool}`" in content
    assert content.count("<!-- neurath:managed -->") == 1
    assert len(content[len(original):].encode()) < 4500
    assert make_plan(repo)["changes"] == []
    apply_plan(repo, make_plan(repo, action="uninstall"))
    assert (repo / "AGENTS.md").read_text() == original


@pytest.mark.parametrize("prefix", ["", "neurath-"])
def test_published_minimal_agents_block_upgrades_without_private_receipt(repo, prefix):
    skills = f"the `{prefix}` skills" if prefix else "the skills"
    previous = (
        "\n<!-- neurath:managed -->\n## Neurath\n\n"
        "Read `.neurath/policy.md` and `.neurath/project.json` for the generic profile.\n"
        f"Use {skills} in `.agents/skills`; use the named MCP task tools. "
        "Consult `.neurath/policy.md` for explicit native execution exceptions.\n"
        "<!-- /neurath:managed -->\n"
    )
    original = "# Project rules\n" + previous + "\n## User additions\nKeep these too.\n"
    (repo / "AGENTS.md").write_text(original)
    apply_plan(repo, make_plan(repo, skill_prefix=prefix))
    content = (repo / "AGENTS.md").read_text()
    assert content.startswith("# Project rules\n")
    assert content.endswith("\n## User additions\nKeep these too.\n")
    assert "`newsroom_publish`" in content
    assert "`memory_pull`" in content
    assert content.count("<!-- neurath:managed -->") == 1
    assert not make_plan(repo)["changes"]


def test_install_enables_native_todo_tools_and_uninstall_restores_config(repo, monkeypatch, tmp_path):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude-home"))
    monkeypatch.delenv("CLAUDE_CODE_ENABLE_TODO_TOOLS", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_ENABLE_TASKS", raising=False)
    original = '# Keep this comment\nmodel = "chosen-model"\n'
    (repo / ".codex").mkdir()
    (repo / ".codex/config.toml").write_text(original)
    apply_plan(repo, make_plan(repo))
    import tomllib
    codex = tomllib.loads((repo / ".codex/config.toml").read_text())
    claude = json.loads((repo / ".claude/settings.json").read_text())
    assert codex["tools"]["update_plan"]["enabled"] is True
    assert codex["model"] == "chosen-model"
    assert claude["env"]["CLAUDE_CODE_ENABLE_TODO_TOOLS"] == "1"
    assert claude["env"]["CLAUDE_CODE_ENABLE_TASKS"] == "0"
    assert not make_plan(repo)["changes"]
    apply_plan(repo, make_plan(repo, action="uninstall"))
    assert (repo / ".codex/config.toml").read_text() == original


@pytest.mark.parametrize("scope", ["project", "global"])
def test_native_todo_defaults_preserve_explicit_user_choices(repo, monkeypatch, tmp_path, scope):
    codex_home, claude_home = tmp_path / "codex-home", tmp_path / "claude-home"
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude_home))
    monkeypatch.delenv("CLAUDE_CODE_ENABLE_TODO_TOOLS", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_ENABLE_TASKS", raising=False)
    codex_path = (repo / ".codex" if scope == "project" else codex_home) / "config.toml"
    claude_path = (repo / ".claude" if scope == "project" else claude_home) / "settings.json"
    codex_path.parent.mkdir(parents=True)
    claude_path.parent.mkdir(parents=True)
    codex_path.write_text('[tools.update_plan]\nenabled = false\n')
    claude_path.write_text(json.dumps({"env": {"CLAUDE_CODE_ENABLE_TASKS": "1",
                                               "CLAUDE_CODE_ENABLE_TODO_TOOLS": "0"}}))
    apply_plan(repo, make_plan(repo))
    import tomllib
    local_codex = tomllib.loads((repo / ".codex/config.toml").read_text())
    local_claude = json.loads((repo / ".claude/settings.json").read_text())
    if scope == "project":
        assert local_codex["tools"]["update_plan"]["enabled"] is False
        assert local_claude["env"]["CLAUDE_CODE_ENABLE_TASKS"] == "1"
        assert local_claude["env"]["CLAUDE_CODE_ENABLE_TODO_TOOLS"] == "0"
    else:
        assert "update_plan" not in local_codex.get("tools", {})
        assert not local_claude.get("env")
        assert tomllib.loads(codex_path.read_text())["tools"]["update_plan"]["enabled"] is False


@pytest.mark.parametrize("option", ["--installation-id", "--receipt"])
def test_restore_plan_accepts_installation_id_and_legacy_option(repo, option, capsys):
    from neurath.cli import main

    record = apply_plan(repo, make_plan(repo))
    plan_path = repo / "restore-plan.json"
    assert main(
        ["--root", str(repo), "plan", "--action", "restore",
         option, record["id"], "--output", str(plan_path)]
    ) == 0
    capsys.readouterr()
    plan = json.loads(plan_path.read_text())
    assert plan["receipt"] == record["id"]
    apply_plan(repo, plan)
    assert not (repo / ".neurath/install.json").exists()


def test_existing_install_adopts_tracked_checkout_bootstrap_without_losing_user_config(repo):
    source = __import__("pathlib").Path(__file__).resolve().parents[1]
    (repo / ".codex").mkdir()
    codex_user = 'model = "user-choice"\n[features]\nuser_feature = true\n'
    (repo / ".codex/config.toml").write_text(codex_user)
    (repo / ".claude").mkdir()
    user_hook = {"hooks": [{"type": "command", "command": "echo user"}]}
    (repo / ".claude/settings.json").write_text(
        json.dumps({"model": "user-choice", "hooks": {"Stop": [user_hook]}}))
    (repo / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"user": {"command": "user-server"}}}))
    apply_plan(repo, make_plan(repo))

    portable = {}
    for name in (".codex/config.toml", ".codex/hooks.json",
                 ".claude/settings.json", ".mcp.json"):
        text = (source / name).read_text()
        if name == ".codex/config.toml":
            text = ("# neurath:checkout-bootstrap\n" + codex_user
                    + "[mcp_servers.neurath_collaboration]"
                    + text.split("[mcp_servers.neurath_collaboration]", 1)[1])
        elif name == ".claude/settings.json":
            settings = json.loads(text)
            settings["model"] = "user-choice"
            settings["hooks"]["Stop"].insert(0, user_hook)
            text = json.dumps(settings, indent=2) + "\n"
        elif name == ".mcp.json":
            config = json.loads(text)
            config["mcpServers"]["user"] = {"command": "user-server"}
            text = json.dumps(config, indent=2) + "\n"
        (repo / name).write_text(text)
        portable[name] = text
    (repo / "tools").mkdir()
    (repo / "tools/checkout_host").write_text("#!/bin/sh\n")
    subprocess.run(["git", "add", "-f", "tools/checkout_host", *portable],
                   cwd=repo, check=True)

    apply_plan(repo, make_plan(repo, action="update"))
    assert {name: (repo / name).read_text() for name in portable} == portable
    assert make_plan(repo)["changes"] == []

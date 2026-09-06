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


@pytest.mark.parametrize("project", ["empty", "python", "javascript"])
def test_both_hosts_preserve_user_files_and_reinstall_is_noop(repo, project):
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
    if project == "python":
        (repo / "pyproject.toml").write_text('[project]\nname="existing"\nversion="1"\n')
    elif project == "javascript":
        (repo / "package.json").write_text('{"name":"existing"}')
    plan = make_plan(repo)
    assert plan["changes"]
    apply_plan(repo, plan)
    assert (repo / "AGENTS.md").read_text().startswith(original)
    installed = json.loads((repo / ".claude/settings.json").read_text())
    assert installed["permissions"] == settings["permissions"]
    assert installed["model"] == "user-choice"
    assert installed["hooks"]["Stop"][0] == settings["hooks"]["Stop"][0]
    assert (repo / ".claude/skills/debug").resolve() == (
        repo / ".agents/skills/debug"
    ).resolve()
    assert not (repo / ".venv").exists()
    assert make_plan(repo)["changes"] == []
    assert read_state(repo)["profile"] == "generic"


def test_stale_plan_refused_without_partial_mutation(repo):
    plan = make_plan(repo)
    (repo / "AGENTS.md").write_text("edited after planning")
    with pytest.raises(InstallError, match="stale"):
        apply_plan(repo, plan)
    assert not (repo / ".codex/hooks.json").exists()


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
    installer._save_json(installer.git_dir(repo) / "neurath-journal.json", plan)
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
    assert (installer.git_dir(repo) / "neurath-journal.json").exists()
    assert installer.recover(repo)["recovered"]
    assert (repo / "AGENTS.md").read_text() == "Original project rules\n"
    assert installer.read_state(repo) is None
    assert not (installer.git_dir(repo) / "neurath-journal.json").exists()
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

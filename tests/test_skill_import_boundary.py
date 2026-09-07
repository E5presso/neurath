"""Bundled Python must not execute modules owned by the target project."""

import os
import shlex
import subprocess
import sys

import pytest


def clean_environment():
    return {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("CODEX_", "CLAUDE", "NEURATH_", "PYTHON"))
    }


def git(root, *arguments):
    return subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True, capture_output=True, text=True, env=clean_environment(),
    )


@pytest.mark.parametrize("shadow", [False, True])
def test_shell_claim_uses_bundled_engine_and_preserves_project_hook_imports(tmp_path, shadow):
    root = tmp_path / "main repository"
    task = tmp_path / "task worktree"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
        "commit", "-qm", "Fixture", "--allow-empty")
    git(root, "worktree", "add", "-qb", "task", str(task))

    # git status in the actual skill invokes this target-owned Python hook.
    # Its sibling imports must still work: no global PYTHONSAFEPATH setting.
    hook_dir = root / ".git/hooks"
    marker = tmp_path / "project-hook-ran"
    (hook_dir / "project_helper.py").write_text(f"MARKER = {str(marker)!r}\n")
    hook_script = hook_dir / "project_fsmonitor.py"
    hook_script.write_text(
        "import sys\nfrom pathlib import Path\nfrom project_helper import MARKER\n"
        "Path(MARKER).write_text('project hook preserved')\n"
        "sys.stdout.buffer.write(b'fixture-token\\0/\\0')\n"
    )
    hook = hook_dir / "project-fsmonitor"
    hook.write_text(
        f"#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(str(hook_script))} \"$@\"\n"
    )
    hook.chmod(0o755)
    git(root, "config", "core.fsmonitor", shlex.quote(str(hook)))

    if shadow:
        package = task / "scripts/agent_harness"
        package.mkdir(parents=True)
        (package.parent / "__init__.py").write_text("")
        (package / "__init__.py").write_text("")
        (package / "state_cli.py").write_text("print('PROJECT_MODULE_EXECUTED')\n")

    result = subprocess.run(
        [sys.executable, "-I", "-m", "neurath", "--root", str(task), "skill",
         "implement-issue", "assert_worktree_isolation.sh", "1"],
        cwd=task, env=clean_environment(), capture_output=True, text=True, timeout=20,
    )
    assert marker.is_file(), result.stdout + result.stderr
    assert marker.read_text() == "project hook preserved"
    assert "PROJECT_MODULE_EXECUTED" not in result.stdout + result.stderr
    assert "isolation-ok" not in result.stdout
    assert result.returncode == 2, result.stdout + result.stderr
    assert "canonical-worktree-claim-rejected" in result.stderr
    assert not (task / ".agents/runs").exists()


def test_direct_monitor_script_keeps_bundled_sibling_imports(tmp_path):
    git(tmp_path, "init", "-q")
    for name in ("app_server_resume", "monitor_check_summary", "monitor_observation_store"):
        (tmp_path / f"{name}.py").write_text("raise RuntimeError('PROJECT_MODULE_EXECUTED')\n")
    result = subprocess.run(
        [sys.executable, "-I", "-m", "neurath", "--root", str(tmp_path), "skill",
         "watch-pr", "local_pr_monitor.py", "--help"],
        cwd=tmp_path, env=clean_environment(), capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert "--workflow-id" in result.stdout
    assert "PROJECT_MODULE_EXECUTED" not in result.stdout + result.stderr

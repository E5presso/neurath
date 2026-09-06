"""Installed mutable state must stay writable without changing host permissions."""

import subprocess
import tomllib

from neurath.runtime.engine import activate
from neurath.install.transaction import apply_plan, make_plan


def test_installed_state_is_outside_host_protected_instructions(tmp_path, monkeypatch):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    config = tmp_path / ".codex/config.toml"
    config.parent.mkdir()
    original = 'sandbox_mode = "workspace-write"\napproval_policy = "never"\n'
    config.write_text(original)
    apply_plan(tmp_path, make_plan(tmp_path))
    monkeypatch.setenv("NEURATH_TARGET_ROOT", str(tmp_path))
    activate(tmp_path)
    from scripts.agent_harness.session_kernel import SessionId, SessionLocator

    locator = SessionLocator.from_worktree(tmp_path)
    assert locator.locate(SessionId("native")).directory == tmp_path / ".neurath/local/runs/native"
    assert locator.worktree_registry_root == tmp_path / ".neurath/local/resources/worktrees"
    assert config.read_text().startswith(original)
    installed = tomllib.loads(config.read_text())
    assert installed["sandbox_mode"] == "workspace-write"
    assert installed["approval_policy"] == "never"
    monkeypatch.delenv("NEURATH_TARGET_ROOT")
    assert locator.locate(SessionId("native")).directory == tmp_path / ".agents/runs/native"

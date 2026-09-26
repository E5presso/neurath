"""Adapter/authority fixtures only; these tests do not validate real provider runs."""

import sys
import subprocess
from types import SimpleNamespace

import pytest

from tests.test_agent_hooks import sessions  # noqa: F401
from tests.test_task_tools import bound_call, claim_fixture
from neurath.agents import mcp


def test_root_worktree_worker_requires_installed_isolated_unclaimed_target(tmp_path, monkeypatch):
    from neurath.runtime.provider_execution import _worktree_worker_preflight
    from scripts.agent_harness.worktree_registry import WorktreeRegistry

    root, target = tmp_path / "repo", tmp_path / "ticket"
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "fixture@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "Fixture"], check=True)
    (root / "README").write_text("fixture\n")
    subprocess.run(["git", "-C", str(root), "add", "README"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "base"], check=True)
    (root / ".git/info/exclude").write_text(".neurath/\n.agents/resources/\n")
    subprocess.run(["git", "-C", str(root), "worktree", "add", "-q", "-b", "issue-1", str(target)], check=True)
    fields = {"worktree": str(target)}
    with pytest.raises(ValueError, match="installed"):
        _worktree_worker_preflight(root, fields)
    (target / ".neurath").mkdir()
    (target / ".neurath/run").write_text("fixture\n")
    _worktree_worker_preflight(root, fields)
    assert not subprocess.run(["git", "-C", str(root), "status", "--porcelain=v1", "--untracked-files=all"],
                              check=True, capture_output=True, text=True).stdout
    monkeypatch.setattr(WorktreeRegistry, "get", lambda *a: object())
    with pytest.raises(ValueError, match="already has an owner"):
        _worktree_worker_preflight(root, fields)
    monkeypatch.undo()
    (target / "dirty").write_text("unrelated work\n")
    with pytest.raises(ValueError, match="target has uncommitted changes"):
        _worktree_worker_preflight(root, fields)
    (target / "dirty").unlink()
    (root / "dirty").write_text("owner work\n")
    with pytest.raises(ValueError, match="root worktree has uncommitted changes"):
        _worktree_worker_preflight(root, fields)


def test_provider_run_exposes_structured_creation_inputs():
    tools = mcp.response(None, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]
    tool = next(item for item in tools if item["name"] == "provider_run")
    fields = tool["inputSchema"]["properties"]
    assert {"worktree", "assignment", "mode", "approval_policy", "key"} <= fields.keys()
    assert "timeout" not in fields
    assert not {"actor", "session", "argv", "available_tools"} & fields.keys()


def test_provider_run_never_uses_missing_caller_policy_as_permission(sessions, monkeypatch):
    root, _ = sessions
    claim_fixture(root)
    monkeypatch.setitem(sys.modules, "neurath.providers.execution",
        SimpleNamespace(run=lambda *a, **k: pytest.fail("provider started without caller policy")))
    bound = bound_call(sessions, "provider_run", {"worktree": str(root), "assignment": "Read only", "purpose": "user-session", "reason": "User continuation"})
    from neurath.runtime.task_schema import TaskError
    with pytest.raises(TaskError, match="readiness") as caught:
        mcp.call_tool(root, bound, name="provider_run")
    assert caught.value.details["code"] == "execution-readiness-required"
    assert "policy" in caught.value.details["message"]


@pytest.mark.parametrize("status", ["accepted", "failed"])
def test_provider_run_cli_and_mcp_share_results(sessions, monkeypatch, status):
    from neurath.cli import main

    root, _ = sessions
    claim_fixture(root)
    native = mcp.AgentIdentity("codex", "api", "codex:session:api")
    monkeypatch.setattr("neurath.agents.identity.current_agent", lambda root: native)
    monkeypatch.setattr("neurath.runtime.tasks._mcp_execution_policy", lambda *a: None)
    # This adapter-parity fixture substitutes the separately tested admission
    # boundary, not the native-policy failure test above.
    monkeypatch.setattr("neurath.runtime.model_tasks.observed_policy", lambda *a: {})
    monkeypatch.setattr("neurath.runtime.model_tasks.admitted_request", lambda root, identity, fields, policy: fields)
    monkeypatch.setattr("neurath.runtime.provider_policy.resolve_policy", lambda root, identity, fields, policy: fields)
    calls = []
    report = {"status": status, "created": {"native_session": "provider-owned-fixture"}}

    def run(*args, **kwargs):
        calls.append((args, kwargs))
        return report

    monkeypatch.setattr("neurath.providers.jobs.start", run)
    emitted = []
    monkeypatch.setattr("neurath.cli.emit", emitted.append)
    assert main(["--root", str(root), "provider", "run", "--worktree", str(root),
                 "--assignment", "Read only", "--purpose", "user-session", "--reason", "User continuation"]) == (0 if status == "accepted" else 1)
    bound = bound_call(sessions, "provider_run", {"worktree": str(root), "assignment": "Read only", "purpose": "user-session", "reason": "User continuation"})
    result = mcp.response(root, {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "provider_run", "arguments": bound}})["result"]
    assert result["structuredContent"]["result"] == emitted[-1] == report
    assert result["isError"] is (status != "accepted")
    assert calls[0] == calls[1]
    assert calls[0][0][2]["model"] is None
    assert calls[0][0][2]["project_id"] is None

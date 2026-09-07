"""Adapter/authority fixtures only; these tests do not validate real provider runs."""

import sys
from types import SimpleNamespace

import pytest

from tests.test_agent_hooks import sessions  # noqa: F401
from tests.test_task_tools import bound_call, claim_fixture
from neurath.agents import mcp


def test_provider_run_exposes_structured_creation_inputs():
    tools = mcp.response(None, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]
    tool = next(item for item in tools if item["name"] == "provider_run")
    fields = tool["inputSchema"]["properties"]
    assert {"worktree", "assignment", "mode", "approval_policy", "timeout"} <= fields.keys()
    assert not {"actor", "session", "argv", "available_tools"} & fields.keys()


def test_provider_run_never_uses_missing_caller_policy_as_permission(sessions, monkeypatch):
    root, _ = sessions
    claim_fixture(root)
    monkeypatch.setitem(sys.modules, "neurath.providers.execution",
        SimpleNamespace(run=lambda *a, **k: pytest.fail("provider started without caller policy")))
    bound = bound_call(sessions, "provider_run", {"worktree": str(root), "assignment": "Read only"})
    with pytest.raises(ValueError, match="execution policy"):
        mcp.call_tool(root, bound, name="provider_run")


@pytest.mark.parametrize("status", ["completed", "timed-out"])
def test_provider_run_cli_and_mcp_share_results(sessions, monkeypatch, status):
    from neurath.cli import main

    root, _ = sessions
    claim_fixture(root)
    native = mcp.AgentIdentity("codex", "api", "codex:session:api")
    monkeypatch.setattr("neurath.agents.identity.current_agent", lambda root: native)
    monkeypatch.setattr("neurath.runtime.tasks._mcp_execution_policy", lambda *a: None)
    calls = []
    report = {"status": status, "created": {"native_session": "provider-owned-fixture"}}

    def run(*args, **kwargs):
        calls.append((args, kwargs))
        return report

    monkeypatch.setitem(sys.modules, "neurath.providers.execution", SimpleNamespace(run=run))
    emitted = []
    monkeypatch.setattr("neurath.cli.emit", emitted.append)
    assert main(["--root", str(root), "provider", "run", "--worktree", str(root),
                 "--assignment", "Read only"]) == (0 if status == "completed" else 1)
    bound = bound_call(sessions, "provider_run", {"worktree": str(root), "assignment": "Read only"})
    result = mcp.response(root, {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "provider_run", "arguments": bound}})["result"]
    assert result["structuredContent"]["result"] == emitted[-1] == report
    assert result["isError"] is (status != "completed")
    assert calls[0] == calls[1]
    assert calls[0][1]["model"] is None

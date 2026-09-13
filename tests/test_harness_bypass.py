"""The kill switch works even when ordinary Neurath hook state is broken."""
import json
import subprocess
import io
import sys

import pytest

from neurath.agents import mcp
from neurath.hosts import hooks
from neurath.runtime.bypass import mode


@pytest.fixture(autouse=True)
def repository(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)


def test_switch_is_reversible_without_hook_binding(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp, "_store", lambda *_: pytest.fail("switch must not require kernel state"))
    assert not mcp.call_tool(tmp_path, {}, name="harness_bypass")["enabled"]
    assert mcp.call_tool(tmp_path, {"enabled": True}, name="harness_bypass")["enabled"]
    assert not mcp.call_tool(tmp_path, {"enabled": False}, name="harness_bypass")["enabled"]


def test_switch_never_opens_the_runtime_database(tmp_path, monkeypatch):
    import sqlite3

    monkeypatch.setattr(sqlite3, "connect", lambda *_args, **_kwargs:
                        pytest.fail("bypass must not initialize or open kernel storage"))
    assert not mode(tmp_path)["enabled"]
    assert mode(tmp_path, True)["enabled"]
    assert mode(tmp_path)["enabled"]
    assert not mode(tmp_path, False)["enabled"]


@pytest.mark.parametrize("event", ["SessionStart", "UserPromptSubmit", "PreToolUse",
    "PostToolUse", "PostToolUseFailure", "PermissionDenied", "Stop", "SubagentStop", "SessionEnd"])
def test_bypass_returns_before_every_neurath_hook_constraint(tmp_path, monkeypatch, event):
    monkeypatch.setattr(hooks, "_dispatch_hook", lambda *_: pytest.fail("hook constraint ran"))
    mode(tmp_path, True)
    assert hooks.hook(tmp_path, "codex", json.dumps({"hook_event_name": event})) == (0, {}, "")


def test_disable_restores_hook_dispatch_and_preserves_worktree_scope(tmp_path, monkeypatch):
    first, other = tmp_path / "one", tmp_path / "other"
    first.mkdir()
    other.mkdir()
    for root in (first, other):
        subprocess.run(["git", "init", "-q", str(root)], check=True)
    mode(first, True)
    assert not mode(other)["enabled"]
    mode(first, False)
    monkeypatch.setattr(hooks, "_dispatch_hook", lambda *_: (2, {}, "normal hook denial"))
    assert hooks.hook(first, "codex", '{"hook_event_name":"Stop"}') == (2, {}, "normal hook denial")


def test_switch_rejects_caller_selected_worktree(tmp_path):
    with pytest.raises(ValueError):
        mcp.call_tool(tmp_path, {"enabled": True, "root": "/different"}, name="harness_bypass")


def test_switch_rejects_symlink_and_does_not_touch_its_target(tmp_path):
    target = tmp_path / "important"
    target.write_text("preserve")
    marker = tmp_path / ".neurath/local/bypass-enabled"
    marker.parent.mkdir(parents=True)
    marker.symlink_to(target)
    for enabled in (None, True, False):
        with pytest.raises(ValueError, match="symlink"):
            mode(tmp_path, enabled)
    assert target.read_text() == "preserve"


def test_switch_hook_does_not_require_normal_session_state(tmp_path, monkeypatch):
    monkeypatch.setattr(hooks, "_dispatch_hook", lambda *_: pytest.fail("switch ran normal admission"))
    assert hooks.hook(tmp_path, "codex", json.dumps({"hook_event_name": "PreToolUse",
        "tool_name": "mcp__neurath_collaboration__harness_bypass",
        "tool_input": {"enabled": True}})) == (0, {}, "")


def test_bypass_does_not_create_identity_for_other_mcp_tools(tmp_path):
    mode(tmp_path, True)
    reply = mcp.response(tmp_path, {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "task_list", "arguments": {}}})["result"]
    assert reply["isError"]
    assert reply["structuredContent"]["error"]["code"] == "native-binding-required"


def test_stdio_switch_works_when_worker_capacity_is_exhausted(tmp_path, monkeypatch):
    from neurath.agents.stdio import StdioCalls

    monkeypatch.setattr(StdioCalls, "submit", lambda *_: pytest.fail("switch needs no worker slot"))
    requests = [
        {"jsonrpc": "2.0", "id": index, "method": "tools/call",
         "params": {"name": "harness_bypass", "arguments": {"enabled": enabled}}}
        for index, enabled in enumerate((True, None, False), 1)
    ]
    monkeypatch.setattr(sys, "argv", ["mcp", "--root", str(tmp_path)])
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(
        ("\n".join(json.dumps(request) for request in requests) + "\n").encode())))
    output = io.StringIO()
    monkeypatch.setattr(sys, "stdout", output)
    assert mcp.main() == 0
    replies = [json.loads(line) for line in output.getvalue().splitlines()]
    assert [reply["result"]["structuredContent"]["result"]["enabled"]
            for reply in replies] == [True, True, False]
    assert not mode(tmp_path)["enabled"]

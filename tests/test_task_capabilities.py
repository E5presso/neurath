"""Capability diagnostics must agree with the public MCP discovery surface."""

import json

import pytest

from neurath.agents import mcp
from neurath.runtime import tasks
from neurath.runtime.task_schema import TASKS
from tests.test_agent_hooks import sessions  # noqa: F401
from tests.test_task_tools import bound_call


def ready_report(*, active=True, direct=True):
    return {
        "is_root": True,
        "implementation_ready": active and direct,
        "stages": {name: {"status": "verified" if active else "unobserved", "evidence": (
            {"approval_policy": "never", "sandbox_policy": {"type": "danger-full-access"}}
            if name == "policy" and direct else {})}
            for name in ("installation", "activation", "policy", "ownership")},
    }


@pytest.mark.parametrize("active,direct", [(True, True), (True, False), (False, False)])
def test_status_never_advertises_an_operation_omitted_from_tools_list(monkeypatch, active, direct):
    monkeypatch.setattr("neurath.providers.readiness.inspect_readiness",
                        lambda root: ready_report(active=active, direct=direct))
    listed = {tool["name"] for tool in mcp.response(None, {
        "jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]}
    operations = tasks.session_status(None, detail="full")["capabilities"][0]["operations"]

    assert set(operations) == set(TASKS)  # Internal compatibility remains discoverable as unavailable.
    assert {name for name, row in operations.items() if row["available"]} <= listed
    for name in set(TASKS) - listed:
        assert operations[name]["implemented"] is True
        assert operations[name]["available"] is False
        assert operations[name]["reason"] == "not-exposed-by-task-mcp"
        assert operations[name]["next_action"]
    assert operations["memory_recall"]["available"] is active
    assert operations["provider_run"]["available"] is (active and direct)


def test_hidden_verification_routes_to_native_checks_and_keeps_legacy_schema(monkeypatch):
    from neurath.runtime.task_schema import arguments

    monkeypatch.setattr("neurath.providers.readiness.inspect_readiness", lambda root: ready_report())
    operations = tasks.session_status(None, detail="full")["capabilities"][0]["operations"]
    for name in ("verification_nodes", "verification_run", "verification_builtin"):
        assert operations[name]["available"] is False
        assert "native" in operations[name]["next_action"]
        assert "permissions" in operations[name]["next_action"]
    assert arguments("verification_nodes", {"nodes": ["tests/test_example.py::test_example"],
                                             "key": "saved-check"})["key"] == "saved-check"
    assert "phase_start" in operations["workflow_start"]["next_action"]


def test_native_bound_mcp_status_matches_public_discovery(sessions):
    from tests.test_identity import native_turn_started

    root, _ = sessions
    transcript = root / "host-storage/api.jsonl"
    transcript.write_text(json.dumps({"type": "session_meta", "payload": {
        "id": "api", "cwd": str(root), "source": "cli"}}) + "\n")
    native_turn_started(transcript, "api-turn")
    bound = bound_call(sessions, "session_status", {"detail": "full"})
    reply = mcp.response(root, {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                              "params": {"name": "session_status", "arguments": bound}})["result"]
    assert reply["isError"] is False
    report = reply["structuredContent"]["result"]
    assert report["stages"]["activation"]["status"] == "verified"
    listed = {tool["name"] for tool in mcp.response(root, {
        "jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]}
    operations = report["capabilities"][0]["operations"]
    assert {name for name, row in operations.items() if row["available"]} <= listed
    for name in ("verification_nodes", "verification_run", "verification_builtin"):
        assert operations[name]["available"] is False
        assert operations[name]["reason"] == "not-exposed-by-task-mcp"

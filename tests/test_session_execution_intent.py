"""Explicit independent work cannot degrade into an unconfigured app session."""

import pytest

from neurath.providers import execution
from neurath.providers.operations import route
from neurath.runtime.task_schema import TaskError, arguments


SETTINGS = {"sandbox": "workspace-write", "approval_policy": "never",
            "collaboration_mode": "default"}


def test_implementation_route_selects_executable_transport_without_app_fallback():
    result = route("codex", "create", worktree="/installed-worktree", assignment="Implement the fix",
                   requested=SETTINGS)
    assert result["next_operation"] == {"tool": "provider_run", "arguments": {
        "worktree": "/installed-worktree", "assignment": "Implement the fix",
        "mode": "workspace-write", "approval_policy": "never", "collaboration_mode": "default"}}
    assert result["implementation_dispatched"] is False
    assert result["mode"]["verification"] == "unobserved"


@pytest.mark.parametrize("scenario,expected", [
    ("not-ready", "not-ready"), ("needs-input", "needs-input"),
    ("approval", "waiting-approval"), ("input", "waiting-input"),
    ("completed", "completed"),
])
def test_preparation_wait_delivery_and_native_completion_are_distinct(monkeypatch, scenario, expected):
    from pathlib import Path
    from neurath.providers.contracts import Session

    calls = []
    inbox_sessions = []
    class Host:
        diagnostic = ""
        def __init__(self, *args, **kwargs):
            request = {"method": "item/commandExecution/requestApproval" if scenario == "approval"
                       else "item/tool/requestUserInput", "id": 1, "params": {"threadId": "native"}}
            self.events = iter([request] if scenario in {"approval", "input"} else [
                {"method": "item/completed", "params": {"threadId": "native",
                    "item": {"type": "commandExecution"}}},
                {"method": "turn/completed", "params": {"threadId": "native", "turn": {
                    "id": "assignment" if scenario == "completed" else "bootstrap", "status": "completed"}}}])
        def event(self, *args, **kwargs): return next(self.events)
        def close(self): pass
    class Adapter:
        def __init__(self, host): pass
        def create(self, *args): return Session("codex", "codex-app-server", "native", "/work", None, "model", {})
        def bootstrap(self, session): return {"delivery": "submitted", "native_turn": "bootstrap"}
        def message(self, session, text):
            calls.append("assignment")
            return {"delivery": "needs-input" if scenario == "needs-input" else "submitted",
                    "native_turn": "assignment"}
        def cancel(self, session): return {"status": "interrupt-requested"}
    monkeypatch.setattr(execution, "_target", lambda *args: Path("/work"))
    monkeypatch.setattr(execution, "CodexStdio", Host)
    monkeypatch.setattr(execution, "CodexSessions", Adapter)
    # This test isolates execution stages with a synthetic host and worktree.
    # Real socket delivery and persistent inbox ownership have separate tests.
    def start_inbox(adapter, session):
        inbox_sessions.append(session.native_session)
        return None
    monkeypatch.setattr(execution, "_start_inbox", start_inbox)
    monkeypatch.setattr(execution, "inspect_owned_session", lambda _: {
        "implementation_ready": scenario != "not-ready", "app_access": {"status": "verified"}})
    result = execution.run("/parent", worktree="/work", assignment="Implement", mode="workspace-write",
                           approval_policy="never", collaboration_mode="default")
    assert result["status"] == expected
    assert result["implementation_dispatched"] is (scenario == "completed")
    assert result["execution"] == ("native-turn-completed" if scenario == "completed" else "unobserved")
    assert inbox_sessions == (["native"] if scenario == "completed" else [])
    if scenario in {"not-ready", "approval", "input"}:
        assert not calls
        assert result["delivery"] == "not-submitted"
    else:
        assert result["preparation"] == "verified"


@pytest.mark.parametrize("missing", list(SETTINGS))
def test_assignment_with_missing_setting_has_no_creation_route(missing):
    result = route("codex", "create", worktree="/installed-worktree", assignment="Implement",
                   requested={key: value for key, value in SETTINGS.items() if key != missing})
    assert result["status"] == "settings-required"
    assert result["next_operation"] is None
    assert result["implementation_dispatched"] is False


def test_manual_approval_request_is_preserved_and_not_replaced_with_never():
    result = route("codex", "create", worktree="/installed-worktree", assignment="Implement",
                   requested={**SETTINGS, "approval_policy": "on-request"})
    assert result["status"] == "unsupported-setting"
    assert result["next_operation"] is None
    assert result["mode"]["requested"]["approval_policy"] == "on-request"


@pytest.mark.parametrize("field", ["approval_policy", "collaboration_mode"])
def test_typed_write_request_rejects_implicit_execution_setting(field):
    fields = {"worktree": "/installed-worktree", "assignment": "Implement", "mode": "workspace-write",
              "approval_policy": "never", "collaboration_mode": "default"}
    del fields[field]
    with pytest.raises(TaskError, match="explicit"):
        arguments("provider_run", fields)


def test_internal_write_run_also_rejects_missing_settings_before_process(monkeypatch):
    monkeypatch.setattr(execution, "_target", lambda *args: pytest.fail("must reject before target access"))
    result = execution.run("/parent", worktree="/work", assignment="Implement", mode="workspace-write")
    assert result["status"] == "settings-required"
    assert result["implementation_dispatched"] is False

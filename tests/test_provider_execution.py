"""The callable execution service withholds assignments until native preparation."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from neurath.providers import execution
from neurath.providers.contracts import Session


@pytest.fixture(autouse=True)
def separate_delivery_unit(monkeypatch):
    # These preparation tests use a synthetic /work. Real socket/owned-connection
    # integration is covered separately in test_provider_supervision.py.
    monkeypatch.setattr(execution, "_start_inbox", lambda *args: None)


@pytest.mark.parametrize("tool_type", ["commandExecution", "mcpToolCall"])
@pytest.mark.parametrize("app_ready", [False, True])
def test_service_never_dispatches_assignment_before_fresh_readiness(monkeypatch, tool_type, app_ready):
    calls = []
    reports = iter([False, True])
    class Host:
        diagnostic = ""
        def __init__(self, *args, **kwargs):
            self.events = iter([
                {"method": "item/completed", "params": {"item": {"type": tool_type}}},
                {"method": "item/completed", "params": {"item": {"type": tool_type}}},
                {"method": "turn/completed", "params": {"turn": {"id": "bootstrap-turn", "status": "completed"}}},
                {"method": "turn/completed", "params": {"turn": {"id": "assignment-turn", "status": "completed"}}},
            ])
        def event(self, *args, **kwargs):
            event = next(self.events)
            if event.get("params", {}).get("turn", {}).get("id") == "bootstrap-turn":
                assert "assignment" not in calls
            if event is None:
                raise TimeoutError("no progress within one event poll")
            return event
        def close(self): calls.append("close")
    class Adapter:
        def __init__(self, host): pass
        def create(self, *args):
            calls.append("create")
            return Session("codex", "codex-app-server", "native", "/work", None, "host-model", {})
        def bootstrap(self, session):
            calls.append("bootstrap")
            return {"native_turn": "bootstrap-turn"}
        def start_after_preparation(self, session, text, preparation_turn):
            assert calls[-1] == "ready"
            assert preparation_turn == "bootstrap-turn"
            calls.append("assignment")
            return {"delivery": "submitted", "native_turn": "assignment-turn"}
    def inspect(session):
        ready = next(reports)
        calls.append("ready" if ready else "not-ready")
        # App observation is independent of native execution readiness.
        return {"implementation_ready": ready,
                "app_access": {"status": "verified" if app_ready else "unverified"}}
    monkeypatch.setattr(execution, "_target", lambda *args: Path("/work"))
    monkeypatch.setattr(execution, "CodexStdio", Host)
    monkeypatch.setattr(execution, "CodexSessions", Adapter)
    monkeypatch.setattr(execution, "inspect_owned_session", inspect)
    result = execution.run("/parent", worktree="/work", assignment="Implement", mode="workspace-write",
                           approval_policy="never", collaboration_mode="default")
    assert result["status"] == "completed"
    assert result["completion"]["id"] == "assignment-turn"
    assert calls == ["create", "bootstrap", "not-ready", "ready", "assignment", "close"]


def test_missing_app_access_does_not_block_native_readiness():
    assert execution._prepared({"implementation_ready": True}, "workspace-write")
    assert execution._prepared({"stages": {name: {"status": "verified"}
        for name in ("installation", "activation", "policy")}}, "read-only")


def test_ordinary_execution_has_no_deadline_and_reports_only_its_submitted_turn(monkeypatch):
    waits, events = [], []
    class Host:
        diagnostic = ""
        def __init__(self, *args, **kwargs):
            assert kwargs["timeout"] == 30  # RPC deadline is separate from task lifetime.
            self.events = iter([
                {"method": "item/completed", "params": {"item": {"type": "commandExecution"}}},
                {"method": "item/started", "params": {"turnId": "unrelated"}},
                {"method": "item/completed", "params": {"item": {
                    "type": "agentMessage", "text": "Preparation only report"}}},
                {"method": "turn/completed", "params": {"turn": {"id": "bootstrap", "status": "completed"}}},
                {"method": "item/started", "params": {"turnId": "work"}},
                {"method": "turn/completed", "params": {"turn": {"id": "work", "status": "completed"}}},
            ])
        def event(self, *args, **kwargs):
            waits.append(kwargs["timeout"])
            return next(self.events)
        def close(self): pass
    class Adapter:
        def __init__(self, host): pass
        def create(self, *args): return Session("codex", "codex-app-server", "native", "/work", None, "model", {})
        def bootstrap(self, session): return {"native_turn": "bootstrap"}
        def start_after_preparation(self, session, prompt, preparation_turn):
            assert preparation_turn == "bootstrap"
            assert "new, separate authorized assignment turn" in prompt
            return {"delivery": "submitted", "native_turn": "work"}
    monkeypatch.setattr(execution, "_target", lambda *args: Path("/work"))
    monkeypatch.setattr(execution, "CodexStdio", Host)
    monkeypatch.setattr(execution, "CodexSessions", Adapter)
    monkeypatch.setattr(execution, "inspect_owned_session", lambda s: {
        "implementation_ready": True, "app_access": {"status": "verified"}})
    result = execution.run("/parent", worktree="/work", assignment="Implement", mode="workspace-write",
        approval_policy="never", collaboration_mode="default", event_callback=lambda *event: events.append(event))
    assert result["status"] == "completed"
    assert waits == [None] * 6
    assert result["preparation_text"] == "Preparation only report"
    assert result["text"] == ""
    assert events[0][0] == "native-created"
    assert events[0][1]["created"]["native_session"] == "native"
    assert events[1:] == [("started", {"native_session": "native", "native_turn": "work"})]


def test_invalid_policy_is_structured_and_cannot_create_a_process(monkeypatch):
    monkeypatch.setattr(execution, "CodexStdio", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError()))
    result = execution.run("/parent", worktree="/work", assignment="Implement", mode="workspace-write",
                           approval_policy="never", collaboration_mode="plan")
    assert result["status"] == "unsupported"
    assert result["implementation_dispatched"] is False
    assert result["retryable"] is False


def _terminal_fixture(monkeypatch, inbox, close_error=None):
    calls = []
    class Host:
        diagnostic = ""
        def __init__(self, *args, **kwargs):
            self.events = iter([
                {"method": "item/completed", "params": {"item": {"type": "commandExecution"}}},
                {"method": "turn/completed", "params": {"turn": {"id": "bootstrap", "status": "completed"}}},
                {"method": "turn/completed", "params": {"turn": {"id": "work", "status": "completed"}}},
                {"method": "turn/completed", "params": {"turn": {"id": "report", "status": "completed"}}}])
        def event(self, *args, **kwargs): return next(self.events)
        def close(self):
            calls.append("host-close")
            if close_error:
                raise close_error
    class Adapter:
        def __init__(self, host): pass
        def create(self, *args): return Session("codex", "codex-app-server", "native", "/work", None, "model", {})
        def bootstrap(self, session): return {"native_turn": "bootstrap"}
        def start_after_preparation(self, session, prompt, preparation_turn):
            assert preparation_turn == "bootstrap"
            return {"delivery": "submitted", "native_turn": "work"}
        def cancel(self, session):
            calls.append("cancel")
            return {"status": "interrupt-requested"}
    monkeypatch.setattr(execution, "_target", lambda *args: Path("/work"))
    monkeypatch.setattr(execution, "CodexStdio", Host)
    monkeypatch.setattr(execution, "CodexSessions", Adapter)
    monkeypatch.setattr(execution, "inspect_owned_session", lambda s: {
        "implementation_ready": True, "app_access": {"status": "verified"}})
    monkeypatch.setattr(execution, "_start_inbox", lambda *args: inbox)
    return calls


@pytest.mark.parametrize("host_error", [None, OSError("fixture host cleanup failed")])
def test_inbox_cleanup_failure_still_closes_host_and_cannot_return_completed(monkeypatch, host_error):
    def close():
        raise OSError("fixture inbox cleanup failed")
    inbox = SimpleNamespace(expected_turn=lambda original: original, pending=lambda: False,
                            complete_turn=lambda *args, **kwargs: "terminal", close=close)
    calls = _terminal_fixture(monkeypatch, inbox, host_error)
    result = execution.run("/parent", worktree="/work", assignment="Work", mode="workspace-write",
                           approval_policy="never", collaboration_mode="default")
    assert calls[-1] == "host-close"
    assert result["status"] == "failed"
    assert result["completion"]["id"] == "work"
    assert [error["stage"] for error in result["cleanup_errors"]] == (
        ["inbox", "host"] if host_error else ["inbox"])


def test_execution_ignores_stale_completion_after_inbox_started_a_report_turn(monkeypatch):
    completed = []
    def decide(turn_id, original, **kwargs):
        completed.append(turn_id)
        return "stale" if turn_id == "work" else "terminal"
    inbox = SimpleNamespace(expected_turn=lambda original: original, pending=lambda: False,
                            complete_turn=decide, close=lambda: None)
    calls = _terminal_fixture(monkeypatch, inbox)
    result = execution.run("/parent", worktree="/work", assignment="Work", mode="workspace-write",
                           approval_policy="never", collaboration_mode="default")
    assert completed == ["work", "report"]
    assert result["completion"]["id"] == "report"
    assert result["status"] == "completed"
    assert calls == ["host-close"]

"""The callable execution service withholds assignments until native preparation."""

from pathlib import Path

import pytest

from neurath.providers import execution
from neurath.providers.contracts import Session


@pytest.mark.parametrize("tool_type", ["commandExecution", "mcpToolCall"])
def test_service_never_dispatches_assignment_before_fresh_readiness(monkeypatch, tool_type):
    calls = []
    reports = iter([False, True])
    class Host:
        diagnostic = ""
        def __init__(self, *args, **kwargs):
            self.events = iter([
                None,
                {"method": "item/completed", "params": {"item": {"type": tool_type}}},
                {"method": "item/completed", "params": {"item": {"type": tool_type}}},
                {"method": "turn/completed", "params": {"turn": {"id": "bootstrap-turn", "status": "completed"}}},
                {"method": "turn/completed", "params": {"turn": {"id": "assignment-turn", "status": "completed"}}},
            ])
        def event(self, *args, **kwargs):
            event = next(self.events)
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
        def message(self, session, text):
            assert calls[-1] == "ready"
            calls.append("assignment")
            return {"delivery": "submitted", "native_turn": "assignment-turn"}
    def inspect(session):
        ready = next(reports)
        calls.append("ready" if ready else "not-ready")
        return {"implementation_ready": ready}
    monkeypatch.setattr(execution, "_target", lambda *args: Path("/work"))
    monkeypatch.setattr(execution, "CodexStdio", Host)
    monkeypatch.setattr(execution, "CodexSessions", Adapter)
    monkeypatch.setattr(execution, "inspect_owned_session", inspect)
    result = execution.run("/parent", worktree="/work", assignment="Implement", mode="workspace-write")
    assert result["status"] == "completed"
    assert result["completion"]["id"] == "assignment-turn"
    assert calls == ["create", "bootstrap", "not-ready", "ready", "assignment", "close"]


def test_invalid_policy_is_structured_and_cannot_create_a_process(monkeypatch):
    monkeypatch.setattr(execution, "CodexStdio", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError()))
    result = execution.run("/parent", worktree="/work", assignment="Implement", mode="workspace-write",
                           collaboration_mode="plan")
    assert result["status"] == "unsupported"
    assert result["implementation_dispatched"] is False
    assert result["retryable"] is False

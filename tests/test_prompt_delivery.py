"""Bookkeeping failures must not suppress human steering or grant tool authority."""

import json
import sqlite3

import pytest

from neurath.hosts import hooks
from neurath.memory.store import MemoryConflict


@pytest.mark.parametrize("host", ["codex", "claude-code"])
@pytest.mark.parametrize("stage", ["session", "memory", "peers"])
@pytest.mark.parametrize(
    "error",
    [MemoryConflict("receipt changed"), sqlite3.OperationalError("locked"), OSError("unavailable")],
)
def test_prompt_is_delivered_on_bookkeeping_failure(tmp_path, monkeypatch, host, stage, error):
    from neurath.memory import hooks as memory
    from neurath.agents import hooks as peers

    monkeypatch.setattr(hooks, "_host_hook", lambda *a, **kw: (0, {}, ""))
    monkeypatch.setattr(memory, "project_event", lambda root, host, payload, output: output)
    monkeypatch.setattr(peers, "peer_event", lambda root, host, payload, output: output)

    def fail(*args, **kwargs):
        raise error

    module, name = {
        "session": (hooks, "_host_hook"),
        "memory": (memory, "project_event"),
        "peers": (peers, "peer_event"),
    }[stage]
    monkeypatch.setattr(module, name, fail)
    code, output, diagnostic = hooks.hook(
        tmp_path,
        host,
        json.dumps(
            {
                "hook_event_name": "UserPromptSubmit",
                "session_id": "root",
                "prompt": "Correction",
            }
        ),
    )
    assert code == 0
    assert "deferred" in diagnostic
    assert "deferred" in output["hookSpecificOutput"]["additionalContext"]
    assert "decision" not in output and "continue" not in output
    if stage == "session":
        with pytest.raises(type(error)):
            hooks.hook(tmp_path, host, json.dumps({"hook_event_name": "PreToolUse"}))
    else:
        assert hooks.hook(tmp_path, host, json.dumps({"hook_event_name": "PreToolUse"}))[0] == 0


@pytest.mark.parametrize("event", ["SessionStart", "PostToolUse"])
def test_optional_memory_failure_preserves_successful_core_output(tmp_path, monkeypatch, event):
    from neurath.memory import hooks as memory
    from neurath.agents import hooks as peers

    core = {"hookSpecificOutput": {"hookEventName": event, "additionalContext": "Verified core context"}}
    monkeypatch.setattr(hooks, "_host_hook", lambda *a, **kw: (0, core, ""))
    def fail(*a):
        raise MemoryConflict("receipt changed")
    monkeypatch.setattr(memory, "project_event", fail)
    monkeypatch.setattr(peers, "peer_event", lambda root, host, payload, output: output)
    code, output, diagnostic = hooks.hook(tmp_path, "codex", json.dumps({"hook_event_name": event}))
    assert code == 0 and "deferred" in diagnostic
    assert "Verified core context" in output["hookSpecificOutput"]["additionalContext"]


@pytest.mark.parametrize("host", ["codex", "claude-code"])
def test_rejected_prompt_reconciliation_does_not_suppress_delivery(tmp_path, monkeypatch, host):
    monkeypatch.setattr(
        hooks,
        "_host_hook",
        lambda *a, **kw: (
            2,
            {"decision": "block", "continue": False},
            "conflicting vendor turn provenance",
        ),
    )
    code, output, diagnostic = hooks.hook(
        tmp_path,
        host,
        json.dumps(
            {
                "hook_event_name": "UserPromptSubmit",
                "session_id": "root",
                "prompt": "Correction",
            }
        ),
    )
    assert code == 0
    assert "deferred" in diagnostic
    assert "decision" not in output and "continue" not in output
    assert hooks.hook(tmp_path, host, json.dumps({"hook_event_name": "PreToolUse"}))[0] == 2

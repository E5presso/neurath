"""Goal reflection is bounded host context, not another task or completion gate."""
import json

import pytest

from tests.test_task_ledger_service import item
from tests.test_workflow_tasks import call

pytest_plugins = ["tests.test_agent_hooks"]


def define(sessions, host, session):
    task = item("user-outcome")
    task["goal"] = "Deliver the requested working integration"
    task["acceptance"] = ["The original user scenario works"]
    return call(sessions, "task_define", {"tasks": [task], "expected_revision": 0,
        "key": "original"}, host=host, session=session)


def context(output):
    return output.get("hookSpecificOutput", {}).get("additionalContext", "")


@pytest.mark.parametrize("host,session", [("codex", "api"), ("claude-code", "ui")])
def test_hooks_periodically_reanchor_without_creating_work(sessions, host, session):
    from neurath.runtime.goal_reminders import TOOL_INTERVAL
    _, invoke = sessions
    defined = define(sessions, host, session)
    def completed(number):
        code, output, diagnostic = invoke(host, session, "PostToolUse", tool_name="Read",
            tool_use_id=f"read-{number}", tool_input={})
        assert code == 0, diagnostic
        return context(output)
    first = completed(0)
    assert "Neurath goal reflection" in first
    assert "Deliver the requested working integration" in first
    assert "The original user scenario works" in first
    assert "method" in first and "task_define" in first
    assert "Neurath goal reflection" not in completed(0)
    for number in range(1, TOOL_INTERVAL):
        assert "Neurath goal reflection" not in completed(number)
    assert "Neurath goal reflection" in completed(TOOL_INTERVAL)
    current = call(sessions, "task_list", {}, host=host, session=session)
    assert current["tasks"] == defined["tasks"]
    assert current["revision"] == defined["revision"]


def test_elapsed_time_and_new_prompt_reanchor_but_duplicate_events_do_not(sessions, monkeypatch):
    from types import SimpleNamespace
    from neurath.runtime import goal_reminders as module
    root, invoke = sessions
    define(sessions, "codex", "api")
    tick = [1000.0]
    monkeypatch.setattr(module, "time", SimpleNamespace(time=lambda: tick[0]))
    payload = {"session_id": "api", "hook_event_name": "PostToolUse",
               "tool_use_id": "one"}
    assert "Neurath goal reflection" in context(module.goal_event(root, "codex", payload, {}))
    tick[0] += module.TIME_INTERVAL + 1
    assert module.goal_event(root, "codex", payload, {}) == {}
    payload["tool_use_id"] = "two"
    assert "Neurath goal reflection" in context(module.goal_event(root, "codex", payload, {}))
    code, output, diagnostic = invoke("codex", "api", "UserPromptSubmit",
        prompt="Please retain the original acceptance", turn_id="api-turn")
    assert code == 0, diagnostic
    assert "Neurath goal reflection" in context(output)
    assert module.goal_event(root, "codex", {"session_id": "api",
        "hook_event_name": "UserPromptSubmit"}, {}) == {}


def test_foreign_child_and_absent_task_list_do_not_receive_root_goals(sessions):
    from neurath.runtime.goal_reminders import goal_event
    root, _ = sessions
    define(sessions, "codex", "api")
    payload = {"session_id": "api", "hook_event_name": "PostToolUse", "tool_use_id": "read"}
    assert goal_event(root, "claude-code", payload, {}) == {}
    assert goal_event(root, "codex", {**payload, "agent_id": "child"}, {}) == {}
    assert goal_event(root, "claude-code", {**payload, "session_id": "ui"}, {}) == {}


def test_failed_goal_is_retained_and_successful_list_does_not_prompt_more_work(sessions):
    from neurath.runtime.goal_reminders import goal_event
    root, _ = sessions
    for host, session, status in (("codex", "api", "failed"), ("claude-code", "ui", "succeeded")):
        defined = define(sessions, host, session)
        task = defined["tasks"][0]
        call(sessions, "task_resolve", {"task_id": task["id"], "expected_revision": 1,
            "expected_task_revision": 1, "key": "result", "references": ["test:result"],
            "status": status, "summary": "Observed result"}, host=host, session=session)
        output = goal_event(root, host, {"session_id": session, "hook_event_name": "PostToolUse",
            "tool_use_id": "after-result"}, {})
        if status == "failed":
            assert "Deliver the requested working integration" in context(output)
            assert "not cancellation" in context(output)
        else:
            assert output == {}


def test_reflection_is_bounded_and_preserves_existing_context(sessions):
    from neurath.runtime.goal_reminders import MAX_BYTES, goal_event
    root, _ = sessions
    tasks = [item(str(i)) for i in range(8)]
    for task in tasks:
        task["goal"] = "원래 요구 " * 500
    call(sessions, "task_define", {"tasks": tasks, "expected_revision": 0, "key": "many"})
    output = goal_event(root, "codex", {"session_id": "api", "hook_event_name": "PostToolUse",
        "tool_use_id": "read"}, {"hookSpecificOutput": {"additionalContext": "Existing context"}})
    text = context(output)
    assert text.startswith("Existing context\n\n")
    assert len(text.removeprefix("Existing context\n\n").encode()) <= MAX_BYTES
    assert "task_list" in text
    assert json.dumps(output, ensure_ascii=False)


@pytest.mark.parametrize("host,session", [("codex", "api"), ("claude-code", "ui")])
@pytest.mark.parametrize("operation", ["task_define", "task_start", "task_resolve"])
def test_task_decisions_reanchor_immediately_without_mutating_ledger(sessions, host, session, operation):
    from neurath.runtime.goal_reminders import goal_event
    root, _ = sessions
    before = define(sessions, host, session)
    goal_event(root, host, {"session_id": session, "hook_event_name": "PostToolUse",
        "tool_use_id": "recent-read"}, {})
    payload = {"session_id": session, "hook_event_name": "PreToolUse",
        "tool_name": "mcp__neurath_collaboration__" + operation,
        "tool_use_id": "decision", "tool_input": {"task_id": before["tasks"][0]["id"]}}
    notice = context(goal_event(root, host, payload, {}))
    assert "Task decision: " + operation in notice
    assert "user requirement" in notice and "scope" in notice
    assert "task_define" in notice and "acceptance" in notice
    assert "Deliver the requested working integration" in notice
    assert goal_event(root, host, payload, {}) == {}
    after = call(sessions, "task_list", {}, host=host, session=session)
    assert after["tasks"] == before["tasks"]
    assert after["revision"] == before["revision"]


def test_first_definition_gets_decision_context_but_ordinary_pretool_does_not(sessions):
    from neurath.runtime.goal_reminders import goal_event
    root, _ = sessions
    payload = {"session_id": "api", "hook_event_name": "PreToolUse", "tool_use_id": "first"}
    assert goal_event(root, "codex", {**payload, "tool_name": "Read"}, {}) == {}
    notice = context(goal_event(root, "codex", {**payload,
        "tool_name": "mcp__neurath_collaboration__task_define"}, {}))
    assert "Task decision: task_define" in notice
    assert "Recorded tasks: 0" in notice


def test_bypass_suppresses_decision_context_and_restoring_enables_it(sessions):
    from neurath.runtime.bypass import mode
    root, invoke = sessions
    define(sessions, "codex", "api")
    fields = dict(tool_name="mcp__neurath_collaboration__task_define", tool_use_id="bypass-define",
                  tool_input={"tasks": [item("follow-up")], "expected_revision": 1, "key": "follow-up"})
    mode(root, True)
    assert invoke("codex", "api", "PreToolUse", **fields) == (0, {}, "")
    mode(root, False)
    code, output, diagnostic = invoke("codex", "api", "PreToolUse", **fields)
    assert code == 0, diagnostic
    assert "Task decision: task_define" in context(output)
    assert output["hookSpecificOutput"]["permissionDecision"] == "allow"


def test_decision_prioritizes_selected_task_beyond_the_first_four(sessions):
    from neurath.runtime.goal_reminders import MAX_BYTES, goal_event
    root, _ = sessions
    result = call(sessions, "task_define", {"tasks": [item(str(i)) for i in range(8)],
        "expected_revision": 0, "key": "many"})
    selected = result["tasks"][-1]["id"]
    notice = context(goal_event(root, "codex", {"session_id": "api", "hook_event_name": "PreToolUse",
        "tool_use_id": "select-last", "tool_name": "mcp__neurath_collaboration__task_start",
        "tool_input": {"task_id": selected}}, {}))
    assert selected in notice
    assert len(notice.encode()) <= MAX_BYTES

"""Native child observations bind prepared work; prompt markers grant no authority."""

import subprocess

import pytest

from neurath.core.domain import CoreError, Phase, Skill
from neurath.core.hook_adapter import HookAdapter
from neurath.core.service import Context, Core


def make_delegation(tmp_path, provider="codex"):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    core = Core(
        tmp_path,
        skills={
            "review": Skill(
                "review", "1", (Phase("inspect", effects=frozenset({"read", "delegate"})),)
            )
        },
    )
    hook = HookAdapter(core, provider)
    hook.handle("SessionStart", {"session_id": "s"}, "start")
    context = Context(f"{provider}:session:s", "s", "input")
    source = core.observe_input(context, "Review the requested change", "prompt")
    task = core.call(
        context,
        "task_define",
        {
            "key": "define",
            "goal": "Review delivered",
            "source_ids": [source.id],
            "acceptance": [{"id": "reviewed"}],
        },
    )["task"]
    for name, extra in [("task_start", {}), ("skill_start", {"skill": "review"})]:
        task = core.call(
            context,
            name,
            {"key": name, "task_id": task["id"], "expected_revision": task["revision"], **extra},
        )["task"]
    prepared = core.call(
        context,
        "assignment_prepare",
        {
            "key": "prepare",
            "task_id": task["id"],
            "expected_revision": task["revision"],
            "execution": "subagent",
            "role": "reviewer",
            "checkout": str(core.store.root),
            "reason": "Independent bounded review",
            "scope": "Inspect this change",
            "subject": "rev1",
        },
    )
    return core, hook, context, task["id"], prepared


@pytest.fixture
def delegation(tmp_path):
    return make_delegation(tmp_path)


def test_claude_resume_reuses_observed_child_and_does_not_consume_fresh_spawn(tmp_path):
    core, hook, context, task_id, prepared = make_delegation(tmp_path, "claude-code")
    payload = {
        "session_id": "s",
        "tool_use_id": "spawn",
        "tool_name": "Agent",
        "tool_input": {"prompt": prepared["dispatch_marker"]},
    }
    assert hook.handle("PreToolUse", payload, "pre") == {}
    hook.handle("SubagentStart", {"session_id": "s", "agent_id": "child"}, "start-child")
    child = "claude-code:agent:child"
    task = core.call(context, "task_read", {"task_id": task_id})["task"]
    followup = core.call(
        context,
        "assignment_prepare",
        {
            "key": "followup",
            "task_id": task_id,
            "expected_revision": task["revision"],
            "execution": "subagent",
            "role": "reviewer",
            "checkout": str(core.store.root),
            "recipient": child,
            "reason": "Continue the independent review",
            "scope": "Inspect correction",
            "subject": "rev2",
        },
    )
    resume = {
        **payload,
        "tool_use_id": "resume",
        "tool_input": {
            "resume": "wrong",
            "prompt": followup["dispatch_marker"],
        },
    }
    assert "native-target-mismatch" in str(hook.handle("PreToolUse", resume, "wrong-resume"))
    resume["tool_input"]["resume"] = "child"
    assert hook.handle("PreToolUse", resume, "resume") == {}
    task = core.call(context, "task_read", {"task_id": task_id})["task"]
    fresh = core.call(
        context,
        "assignment_prepare",
        {
            "key": "fresh",
            "task_id": task_id,
            "expected_revision": task["revision"],
            "execution": "subagent",
            "role": "reviewer",
            "checkout": str(core.store.root),
            "reason": "Another review",
            "scope": "Other scope",
            "subject": "rev2",
        },
    )
    assert (
        hook.handle(
            "PreToolUse",
            {**payload, "tool_use_id": "fresh", "tool_input": {"prompt": fresh["dispatch_marker"]}},
            "fresh",
        )
        == {}
    )
    hook.handle("SubagentStart", {"session_id": "s", "agent_id": "child"}, "resume-start")
    hook.handle("SubagentStart", {"session_id": "s", "agent_id": "new-child"}, "fresh-start")
    result = core.call(
        context, "assignment_read", {"task_id": task_id, "assignment_id": fresh["assignment"]["id"]}
    )
    assert result["assignment"]["recipient"] == "claude-code:agent:new-child"


def test_start_observation_binds_child_without_new_session_or_project(delegation):
    core, hook, context, task_id, prepared = delegation
    payload = {
        "session_id": "s",
        "tool_use_id": "spawn",
        "tool_name": "spawn_agent",
        "tool_input": {
            "task_name": "reader",
            "fork_turns": "none",
            "message": prepared["dispatch_marker"],
        },
    }
    assert hook.handle("PreToolUse", payload, "pre") == {}
    hook.handle("SubagentStart", {"session_id": "s", "agent_id": "child"}, "child-start")
    hook.handle("PostToolUse", {**payload, "tool_response": {"task_name": "/root/reader"}}, "post")
    child = Context("codex:agent:child", "s", "begin")
    result = core.call(
        child,
        "assignment_start",
        {"key": "begin", "task_id": task_id, "assignment_id": prepared["assignment"]["id"]},
    )
    assert result["assignment"]["recipient"] == child.actor_id
    assert (
        core.call(context, "collaboration_discover", {})["actors"][0]["native_handle"] is not None
    )
    with core.store.transaction() as tx:
        assert tx.db.execute("SELECT COUNT(*) FROM leases").fetchone()[0] == 0
    task = core.call(context, "task_read", {"task_id": task_id})["task"]
    with pytest.raises(CoreError, match="assignments-unsettled"):
        core.call(
            context,
            "phase_complete",
            {
                "key": "premature",
                "task_id": task_id,
                "expected_revision": task["revision"],
                "phase_id": "inspect",
                "outcomes": {},
                "inputs": {},
            },
        )


def test_unprepared_spawn_and_nonfresh_reviewer_are_denied(delegation):
    _, hook, _, _, prepared = delegation
    payload = {
        "session_id": "s",
        "tool_use_id": "spawn",
        "tool_name": "spawn_agent",
        "tool_input": {"task_name": "reader", "message": "Unregistered work"},
    }
    assert (
        "assignment-marker-required"
        in hook.handle("PreToolUse", payload, "pre")["hookSpecificOutput"][
            "permissionDecisionReason"
        ]
    )
    payload["tool_input"]["message"] = prepared["dispatch_marker"]
    assert (
        "fresh-review-context-required"
        in hook.handle("PreToolUse", payload, "pre2")["hookSpecificOutput"][
            "permissionDecisionReason"
        ]
    )


def test_native_child_handback_requires_its_report_but_not_parent_acceptance(tmp_path):
    core, hook, context, task_id, prepared = make_delegation(tmp_path, "claude-code")
    spawn = {
        "session_id": "s",
        "tool_use_id": "spawn",
        "tool_name": "Agent",
        "tool_input": {"prompt": prepared["dispatch_marker"]},
    }
    assert hook.handle("PreToolUse", spawn, "pre-spawn") == {}
    hook.handle("SubagentStart", {"session_id": "s", "agent_id": "child"}, "child-start")
    handback = {
        "session_id": "s",
        "agent_id": "child",
        "tool_use_id": "return",
        "tool_name": "SubagentHandback",
        "tool_input": {"message": "Actual result"},
    }
    assert "assignment-unsettled" in str(hook.handle("PreToolUse", handback, "early-return"))
    child = Context("claude-code:agent:child", "s", "report")
    core.call(
        child,
        "assignment_report",
        {
            "key": "report",
            "task_id": task_id,
            "assignment_id": prepared["assignment"]["id"],
            "verdict": "pass",
            "body": "Read actual source",
            "subject": "rev1",
        },
    )
    assert hook.handle("PreToolUse", handback, "return-after-report") == {}
    assert not core.stop(context)["allowed"]

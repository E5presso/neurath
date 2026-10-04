"""Native recipient termination preserves the user goal and permits result settlement."""

import subprocess
from uuid import uuid4

import pytest

from neurath.core.domain import Phase, Skill
from neurath.core.hook_adapter import HookAdapter
from neurath.core.service import Context, Core


def setup(root, effects):
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    core = Core(
        root, skills={"test": Skill("test", "1", (Phase("phase", effects=frozenset(effects)),))}
    )
    hook = HookAdapter(core, "codex")
    hook.handle("SessionStart", {"session_id": "owner"}, "start")
    context = Context("codex:session:owner", "owner", "fixture")

    def call(name, **values):
        return core.call(context, name, {"key": uuid4().hex, **values})

    source = core.observe_input(context, "Perform the requested work.", "input")
    task = call(
        "task_define", goal="Deliver result", source_ids=[source.id], acceptance=[{"id": "done"}]
    )["task"]
    for name, values in [("task_start", {}), ("skill_start", {"skill": "test"})]:
        task = call(name, task_id=task["id"], expected_revision=task["revision"], **values)["task"]
    return core, hook, context, task, call


@pytest.mark.parametrize("provider", ["codex", "claude-code"])
def test_terminated_cancelled_recipient_can_be_settled_without_completing_goal(tmp_path, provider):
    core, hook, owner, task, call = setup(tmp_path, {"read", "delegate"})
    peer_hook = HookAdapter(core, provider)
    peer_hook.handle("SessionStart", {"session_id": "peer"}, "peer-start")
    peer = Context(provider + ":session:peer", "peer", "peer-call")
    assignment = call(
        "assignment_prepare",
        task_id=task["id"],
        expected_revision=task["revision"],
        execution="session" if provider == "codex" else "cross-provider",
        provider=provider,
        recipient=peer.actor_id,
        role="worker",
        reason="Bounded work",
        scope="Inspect",
        subject="v1",
    )["assignment"]
    core.call(
        peer,
        "assignment_start",
        {"key": "start", "task_id": task["id"], "assignment_id": assignment["id"]},
    )
    call(
        "assignment_cancel",
        task_id=task["id"],
        assignment_id=assignment["id"],
        reason="Cancel this attempt",
    )
    peer_hook.handle("SessionEnd", {"session_id": "peer"}, "native-end")
    result = core.call(
        owner, "assignment_read", {"task_id": task["id"], "assignment_id": assignment["id"]}
    )["assignment"]
    assert result["state"] == "reported" and result["verdict"] == "cancelled"
    source = core.call(owner, "source_read", {"source_id": result["result_source"]})
    assert source["kind"] == "tool"
    call(
        "assignment_reject",
        task_id=task["id"],
        assignment_id=assignment["id"],
        source_id=result["result_source"],
    )
    assert core.call(owner, "task_read", {"task_id": task["id"]})["task"]["state"] == "running"
    assert core.stop(owner)["pending"][0]["reason"] == "task-unfinished"


def test_session_end_returns_same_session_executor_responsibility_for_adoption(tmp_path):
    core, hook, owner, task, call = setup(tmp_path, {"read", "delegate"})
    hook.handle("SubagentStart", {"session_id": "owner", "agent_id": "child"}, "child-start")
    child = Context("codex:agent:child", "owner", "child-call")
    other_hook = HookAdapter(core, "claude-code")
    other_hook.handle("SessionStart", {"session_id": "owner"}, "independent-provider")
    assignment = call(
        "assignment_prepare",
        task_id=task["id"],
        expected_revision=task["revision"],
        execution="subagent",
        recipient=child.actor_id,
        role="executor",
        reason="Run the procedure",
        scope="Current Task",
        subject="v1",
    )["assignment"]
    core.call(
        child,
        "assignment_start",
        {"key": "start", "task_id": task["id"], "assignment_id": assignment["id"]},
    )
    hook.handle("SessionEnd", {"session_id": "owner"}, "whole-session-ended")
    with core.store.transaction() as tx:
        assert tx.record("actor", child.actor_id)["value"]["status"] == "stopped"
        assert tx.record("actor", "claude-code:session:owner")["value"]["status"] == "active"
    hook.handle("SessionStart", {"session_id": "replacement"}, "replacement-start")
    replacement = Context("codex:session:replacement", "replacement", "resume")
    source = core.observe_input(
        replacement, "Continue the interrupted Task.", "continuation-instruction"
    )
    retained = core.call(replacement, "task_read", {"task_id": task["id"]})["task"]
    adopted = core.call(
        replacement,
        "task_adopt",
        {
            "key": "adopt",
            "task_id": task["id"],
            "expected_revision": retained["revision"],
            "source_id": source.id,
            "start": 0,
            "end": len(source.text),
            "digest": source.digest,
            "reason": "User requested continuation",
        },
    )["task"]
    ended = adopted["assignments"][0]
    assert ended["state"] == "reported" and ended["verdict"] == "failed"
    core.call(
        replacement,
        "assignment_reject",
        {
            "key": "settle-ended-executor",
            "task_id": task["id"],
            "assignment_id": ended["id"],
            "source_id": ended["result_source"],
        },
    )
    retained = core.call(replacement, "task_read", {"task_id": task["id"]})["task"]
    core.call(
        replacement,
        "phase_complete",
        {
            "key": "resume-phase",
            "task_id": task["id"],
            "expected_revision": retained["revision"],
            "phase_id": "phase",
            "outcomes": {},
            "inputs": {},
        },
    )
    assert not core.stop(replacement)["allowed"]

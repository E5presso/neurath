"""Effects are checked against the current skill phase at the host boundary."""

import subprocess

import pytest

from neurath.core.domain import Condition, CoreError, Phase, Skill
from neurath.core.service import Context, Core


@pytest.fixture
def setup(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    core = Core(
        tmp_path,
        skills={
            "work": Skill(
                "work",
                "1",
                (
                    Phase("read", (Condition("understood"),)),
                    Phase("edit", (), frozenset({"read", "edit", "check"})),
                ),
            )
        },
    )
    core.observe_actor("root", "session", "codex")
    context = Context("root", "session", "event")
    source = core.observe_user(context, "Implement the requirement", "prompt")
    task = core.call(
        context,
        "task_define",
        {
            "key": "define",
            "goal": "Requirement works",
            "source_ids": [source.id],
            "acceptance": [{"id": "works"}],
        },
    )["task"]
    for name, data in [("task_start", {}), ("skill_start", {"skill": "work"})]:
        task = core.call(
            context,
            name,
            {"key": name, "task_id": task["id"], "expected_revision": task["revision"], **data},
        )["task"]
    return core, context, task, tmp_path


def advance(core, context, task):
    evidence = core.call(
        context,
        "report_record",
        {"key": "report", "task_id": task["id"], "body": "Scope checked", "passed": True},
    )["evidence"]
    return core.call(
        context,
        "phase_complete",
        {
            "key": "phase",
            "task_id": task["id"],
            "expected_revision": task["revision"],
            "phase_id": "read",
            "outcomes": {"understood": [evidence["id"]]},
            "inputs": {},
        },
    )["task"]


def test_read_does_not_require_task_focus_claim_or_policy(setup):
    core, _, _, _ = setup
    core.observe_actor("reader", "child-session", "claude-code")
    assert core.admit(Context("reader", "child-session", "read"), {"read"})["allowed"]


def test_phase_denies_edit_even_when_writer_owns_checkout(setup):
    core, context, task, root = setup
    lease = core.call(
        context, "worktree_claim", {"key": "claim", "task_id": task["id"], "checkout": str(root)}
    )["lease"]
    with pytest.raises(CoreError, match="effect-out-of-phase"):
        core.admit(context, {"edit"}, checkout_path=root, generation=lease["generation"])
    assert core.stop(context)["allowed"] is False


def test_allowed_edit_requires_current_lease_and_tracks_implementer(setup):
    core, context, task, root = setup
    task = advance(core, context, task)
    with pytest.raises(CoreError, match="writer-lease-required"):
        core.admit(context, {"edit"}, checkout_path=root)
    lease = core.call(
        context, "worktree_claim", {"key": "claim", "task_id": task["id"], "checkout": str(root)}
    )["lease"]
    with pytest.raises(CoreError, match="stale-lease"):
        core.admit(context, {"edit"}, checkout_path=root, generation=lease["generation"] + 1)
    admitted = core.admit(context, {"edit"}, checkout_path=root, generation=lease["generation"])
    assert admitted["task_id"] == task["id"]
    assert core.call(context, "task_read", {"task_id": task["id"]})["task"][
        "implementation_actors"
    ] == ["root"]


def test_unknown_execution_cannot_escape_read_phase(setup):
    core, context, _, _ = setup
    with pytest.raises(CoreError, match="effect-out-of-phase"):
        core.admit(context, {"execute"})


def test_checks_do_not_need_writer_lease(setup):
    core, context, task, _ = setup
    advance(core, context, task)
    assert core.admit(context, {"check"})["allowed"]


def test_publication_needs_interpreted_consent_for_the_exact_native_target(setup):
    core, context, task, root = setup
    from dataclasses import replace

    from neurath.core.domain import Phase, Skill

    # This fixture's release phase is explicit, not reached by skipping its read phase.
    core.skills["release"] = Skill(
        "release", "1", (Phase("publish", effects=frozenset({"publish"})),)
    )
    task = advance(core, context, task)
    task = core.call(
        context,
        "phase_complete",
        {
            "key": "edit-finished",
            "task_id": task["id"],
            "expected_revision": task["revision"],
            "phase_id": "edit",
            "outcomes": {},
            "inputs": {},
        },
    )["task"]
    task = core.call(
        context,
        "skill_start",
        {
            "key": "release",
            "task_id": task["id"],
            "expected_revision": task["revision"],
            "skill": "release",
        },
    )["task"]
    target = {"command": "git push origin branch", "cwd": str(root)}
    with pytest.raises(CoreError, match="approval-required"):
        core.admit(context, {"publish"}, effect_target=target)
    source = core.observe_input(context, "Publish the verified change.", "publish")
    core.call(
        replace(context, invocation_id="approval"),
        "approval_record",
        {
            "key": "approval",
            "task_id": task["id"],
            "source_id": source.id,
            "start": 0,
            "end": len(source.text),
            "digest": source.digest,
            "action": "publish",
            "target": target,
            "reason": "Current user authorized publication.",
        },
    )
    assert core.admit(context, {"publish"}, effect_target=target)["allowed"]
    with pytest.raises(CoreError, match="approval-required"):
        core.admit(
            context, {"publish"}, effect_target={**target, "command": "git push different branch"}
        )

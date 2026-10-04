"""Observed native cleanup retains checked bytes without making reports authoritative."""

import shlex
from pathlib import Path

import pytest

from neurath.core.domain import CoreError, Phase, Skill
from neurath.core.hook_adapter import HookAdapter
from neurath.core.service import Context, Core
from neurath.core.workspace import source_subject
from tests.core.test_workspace import git


def test_deleted_checkout_keeps_check_evidence_only_after_observed_native_cleanup(tmp_path):
    root, linked = tmp_path / "repo", tmp_path / "linked"
    root.mkdir()
    git(root, "init", "-q")
    git(
        root,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "--allow-empty",
        "-qm",
        "initial",
    )
    git(root, "worktree", "add", "-qb", "task", str(linked))
    core = Core(
        root,
        skills={
            "cleanup": Skill("cleanup", "1", (Phase("cleanup", effects=frozenset({"cleanup"})),))
        },
    )
    hook = HookAdapter(core, "codex")
    hook.handle("SessionStart", {"session_id": "s"}, "start")
    context = Context("codex:session:s", "s", "call")
    source = core.observe_input(context, "Complete and clean up the checkout", "input")
    task = core.call(
        context,
        "task_define",
        {
            "key": "define",
            "goal": "Delivered",
            "source_ids": [source.id],
            "acceptance": [{"id": "checked", "kinds": ["check"]}],
        },
    )["task"]
    for name, extra in [("task_start", {}), ("skill_start", {"skill": "cleanup"})]:
        task = core.call(
            context,
            name,
            {"key": name, "task_id": task["id"], "expected_revision": task["revision"], **extra},
        )["task"]
    core.call(
        context, "worktree_claim", {"key": "claim", "checkout": str(linked), "task_id": task["id"]}
    )
    evidence = core.observe_tool(
        context,
        task["id"],
        "actual-check",
        {"exit_code": 0, "passed": True},
        kind="check",
        subject=source_subject(linked),
        checkout_path=str(linked),
    )
    payload = {
        "session_id": "s",
        "cwd": str(root),
        "tool_name": "exec_command",
        "tool_use_id": "remove",
        "tool_input": {
            "cmd": shlex.join(["git", "worktree", "remove", str(linked)]),
            "workdir": str(root),
        },
    }
    assert hook.handle("PreToolUse", payload, "pre-remove") == {}
    git(root, "worktree", "remove", str(linked))
    task = core.call(context, "task_read", {"task_id": task["id"]})["task"]
    task = core.call(
        context,
        "phase_complete",
        {
            "key": "phase",
            "task_id": task["id"],
            "expected_revision": task["revision"],
            "phase_id": "cleanup",
            "inputs": {},
            "outcomes": {},
        },
    )["task"]
    values = {
        "key": "complete",
        "task_id": task["id"],
        "expected_revision": task["revision"],
        "outcomes": {"checked": [evidence.id]},
    }
    with pytest.raises(CoreError, match="evidence-subject-unavailable"):
        core.call(context, "task_complete", values)
    hook.handle(
        "PostToolUse", {**payload, "tool_response": {"exit_code": 0, "output": ""}}, "post-remove"
    )
    assert core.call(context, "task_complete", values)["task"]["state"] == "completed"
    assert not Path(linked).exists()

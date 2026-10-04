"""Writer coordination and workflow completion are separate from native permissions."""

import subprocess

import pytest

from neurath.core.commands import Context
from neurath.core.domain import CoreError, Phase, Skill
from neurath.core.hook_adapter import HookAdapter
from neurath.core.service import Core


@pytest.fixture
def setup(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    core = Core(
        tmp_path, skills={"work": Skill("work", "1", (Phase("analysis"), Phase("delivery")))}
    )
    hook = HookAdapter(core, "codex")
    hook.handle("SessionStart", {"session_id": "s"}, "start")
    context = Context("codex:session:s", "s", "call")
    source = core.provenance.observe_input(context, "Deliver the requested result", "input")
    task = core.call(
        context,
        "task_define",
        {
            "key": "define",
            "goal": "Delivered",
            "source_ids": [source.id],
            "acceptance": [{"id": "done"}],
        },
    )["task"]
    for name, extra in [("task_start", {}), ("skill_start", {"skill": "work"})]:
        task = core.call(
            context,
            name,
            {"key": name, "task_id": task["id"], "expected_revision": task["revision"], **extra},
        )["task"]
    return core, hook, context, task, tmp_path


@pytest.mark.parametrize(
    "tool,values",
    [
        ("exec_command", {"cmd": "git status\ntouch file"}),
        ("Bash", {"command": "git push origin branch"}),
        ("write_stdin", {"session_id": 123, "chars": "next input\n"}),
        ("unknown_native_tool", {}),
    ],
)
def test_native_calls_neither_grant_permissions_nor_advance_workflow(setup, tool, values):
    core, hook, context, task, root = setup
    assert (
        hook.handle(
            "PreToolUse",
            {
                "session_id": "s",
                "tool_name": tool,
                "tool_use_id": "call",
                "cwd": str(root),
                "tool_input": values,
            },
            "pre",
        )
        == {}
    )
    current = core.call(context, "task_read", {"task_id": task["id"]})["task"]
    assert current["revision"] == task["revision"]
    with pytest.raises(CoreError, match="phase-order"):
        core.call(
            context,
            "phase_complete",
            {
                "key": "skip",
                "task_id": task["id"],
                "expected_revision": task["revision"],
                "phase_id": "delivery",
                "outcomes": {},
                "inputs": {},
            },
        )
    with pytest.raises(CoreError, match="phases-unfinished"):
        core.call(
            context,
            "task_complete",
            {
                "key": "early",
                "task_id": task["id"],
                "expected_revision": task["revision"],
                "outcomes": {},
            },
        )
    assert not core.sessions.stop(context)["allowed"]


def test_explicit_editor_requires_current_writer_without_phase_permission_model(setup):
    core, hook, context, task, root = setup
    with pytest.raises(CoreError, match="writer-lease-required"):
        core.ownership.admit_write(context, checkout_path=root, generation=None)
    lease = core.call(
        context, "worktree_claim", {"key": "claim", "task_id": task["id"], "checkout": str(root)}
    )["lease"]
    with pytest.raises(CoreError, match="stale-lease"):
        core.ownership.admit_write(context, checkout_path=root, generation=lease["generation"] + 1)
    assert core.ownership.admit_write(context, checkout_path=root, generation=lease["generation"])[
        "allowed"
    ]
    assert core.call(context, "phase_read", {"task_id": task["id"]})["phase"]["id"] == "analysis"
    core.sessions.observe_actor("other", "other-session", "codex")
    with pytest.raises(CoreError, match="lease-conflict"), core.store.transaction() as tx:
        tx.claim(str(root), "other")


def test_structured_editor_paths_are_literal_not_shell_patterns(setup):
    core, hook, context, task, root = setup
    core.call(
        context,
        "worktree_claim",
        {"key": "claim-literal", "task_id": task["id"], "checkout": str(root)},
    )
    result = hook.handle(
        "PreToolUse",
        {
            "session_id": "s",
            "cwd": str(root),
            "tool_name": "Write",
            "tool_use_id": "literal-write",
            "tool_input": {"file_path": str(root / "[literal].txt"), "content": "source"},
        },
        "write",
    )
    assert result == {}

"""Input to a retained terminal is an effect, not an output poll."""

import subprocess

from neurath.core.domain import Phase, Skill
from neurath.core.hook_adapter import HookAdapter
from neurath.core.service import Context, Core


def test_terminal_input_rechecks_current_phase_and_original_writer_target(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    core = Core(
        tmp_path,
        skills={
            "work": Skill(
                "work",
                "1",
                (
                    Phase("execute", effects=frozenset({"execute", "read"})),
                    Phase("review"),
                ),
            )
        },
    )
    hook = HookAdapter(core, "codex")
    hook.handle("SessionStart", {"session_id": "s"}, "start")
    context = Context("codex:session:s", "s", "call")
    source = core.observe_input(context, "Perform and review the work", "prompt")
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
    core.call(
        context,
        "worktree_claim",
        {"key": "claim", "checkout": str(tmp_path), "task_id": task["id"]},
    )
    shell = {
        "session_id": "s",
        "tool_name": "exec_command",
        "tool_use_id": "shell",
        "cwd": str(tmp_path),
        "tool_input": {"cmd": "/bin/sh", "workdir": str(tmp_path)},
    }
    assert hook.handle("PreToolUse", shell, "pre") == {}
    hook.handle(
        "PostToolUse", {**shell, "tool_response": {"session_id": 123, "output": ""}}, "post"
    )
    stdin = {
        "session_id": "s",
        "tool_name": "write_stdin",
        "tool_use_id": "stdin",
        "cwd": str(tmp_path),
        "tool_input": {"session_id": 123, "chars": "printf ready\n"},
    }
    assert hook.handle("PreToolUse", stdin, "write") == {}
    task = core.call(context, "task_read", {"task_id": task["id"]})["task"]
    core.call(
        context,
        "phase_complete",
        {
            "key": "advance",
            "task_id": task["id"],
            "expected_revision": task["revision"],
            "phase_id": "execute",
            "outcomes": {},
            "inputs": {},
        },
    )
    assert "effect-out-of-phase" in str(hook.handle("PreToolUse", stdin, "write-again"))
    for chars in ("", "\x03"):
        assert (
            hook.handle(
                "PreToolUse",
                {**stdin, "tool_input": {"session_id": 123, "chars": chars}},
                "control",
            )
            == {}
        )

"""A native-owned subprocess supplies exit evidence; printed claims cannot."""

import json
import subprocess
import sys

import pytest

from neurath.core.check_job import run
from neurath.core.domain import Condition, CoreError, Phase, Skill
from neurath.core.hook_adapter import HookAdapter
from neurath.core.service import Context, Core


@pytest.mark.parametrize("exit_code", [0, 7])
def test_prepared_native_check_records_real_exit_not_printed_json(tmp_path, exit_code):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    directory = tmp_path / ".neurath"
    directory.mkdir()
    (directory / "project.json").write_text(
        json.dumps(
            {
                "verification": {
                    "probe": {
                        "argv": [
                            sys.executable,
                            "-c",
                            f"print('{{\"exit_code\":0}}');raise SystemExit({exit_code})",
                        ],
                        "cwd": ".",
                        "success_codes": [0],
                    }
                }
            }
        )
    )
    core = Core(
        tmp_path,
        skills={
            "test": Skill(
                "test",
                "1",
                (
                    Phase(
                        "verify",
                        (Condition("checked", frozenset({"check"})),),
                        frozenset({"check"}),
                    ),
                ),
            )
        },
    )
    context = Context("codex:session:s", "s", "fixture")
    core.observe_actor(context.actor_id, context.session_id, "codex")
    source = core.observe_input(context, "Check the declared result", "input")
    task = core.call(
        context,
        "task_define",
        {
            "key": "define",
            "goal": "Verified result",
            "source_ids": [source.id],
            "acceptance": [{"id": "done"}],
        },
    )["task"]
    for name, extra in [("task_start", {}), ("skill_start", {"skill": "test"})]:
        task = core.call(
            context,
            name,
            {"key": name, "task_id": task["id"], "expected_revision": task["revision"], **extra},
        )["task"]
    prepared = core.call(
        context,
        "verification_prepare",
        {"key": "check", "task_id": task["id"], "checkout": str(tmp_path), "check_name": "probe"},
    )
    identifier = prepared["execution"]["id"]
    with pytest.raises(CoreError, match="native-check-launch-required"):
        run(core, identifier)
    result = HookAdapter(core, "codex").handle(
        "PreToolUse",
        {
            "session_id": "s",
            "tool_use_id": "actual-launch",
            "tool_name": "exec_command",
            "tool_input": prepared["native_action"]["arguments"],
            "cwd": str(tmp_path),
        },
        "native-pre",
    )
    assert result == {}, result
    result = run(core, identifier)
    assert result["result"]["exit_code"] == exit_code
    assert result["result"]["passed"] is (exit_code == 0)
    with pytest.raises(CoreError, match="native-check-launch-required"):
        run(core, identifier)
    evidence = core.call(context, "evidence_list", {"task_id": task["id"]})["evidence"][0][
        "evidence"
    ]
    assert evidence["passed"] is (exit_code == 0)


def test_check_timeout_is_an_attempt_failure_not_an_observed_test_result(tmp_path):
    from neurath.core.check_job import execute

    with pytest.raises(subprocess.TimeoutExpired):
        execute(
            {
                "argv": [sys.executable, "-c", "import time;time.sleep(60)"],
                "cwd": str(tmp_path),
                "success_codes": [0],
                "timeout_seconds": 0.05,
            }
        )


def test_native_check_does_not_accept_a_surviving_owned_process(tmp_path):
    from neurath.core.check_job import execute

    program = 'import subprocess; subprocess.Popen(["sleep","60"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)'
    result = execute(
        {
            "argv": [sys.executable, "-c", program],
            "cwd": str(tmp_path),
            "success_codes": [0],
            "timeout_seconds": 2,
        }
    )
    assert result["exit_code"] == 0
    assert result["owned_processes_survived"] and not result["passed"]

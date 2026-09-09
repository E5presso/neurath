"""Real hook entry points must deliver shared memory, not just expose a store API."""

import json
import os
import subprocess

import pytest
from neurath.install.transaction import apply_plan, make_plan


@pytest.fixture
def installed(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    apply_plan(tmp_path, make_plan(tmp_path))
    return tmp_path


def invoke(root, host, session, event, **fields):
    env = {
        k: v for k, v in os.environ.items() if not k.startswith(("NEURATH_", "CODEX_", "CLAUDE_"))
    }
    return subprocess.run(
        [str(root / ".neurath/run"), "hook", "--host", host],
        input=json.dumps(
            {"cwd": str(root), "session_id": session, "hook_event_name": event, **fields}
        ),
        capture_output=True,
        text=True,
        env=env,
    )


@pytest.mark.parametrize("first,second", [("codex", "claude-code"), ("claude-code", "codex")])
def test_fresh_session_receives_previous_host_goal(installed, first, second):
    assert invoke(installed, first, "old", "SessionStart", source="startup").returncode == 0
    prompt = invoke(
        installed,
        first,
        "old",
        "UserPromptSubmit",
        prompt="Work log CSV must preserve Korean filenames",
        turn_id="old-turn",
    )
    assert prompt.returncode == 0, prompt.stderr
    new = invoke(installed, second, "new", "SessionStart", source="startup")
    assert new.returncode == 0, new.stderr
    assert "Work log CSV must preserve Korean filenames" in new.stdout
    assert "reference-only" in new.stdout
    from neurath.runtime.engine import activate
    activate(installed)
    from scripts.agent_harness.session_kernel import SessionKernel, SessionLocator, SessionId
    state = SessionKernel(SessionLocator(installed)).inspect(SessionId("new")).to_payload()
    assert not state["workflows"]
    assert state["session"]["id"] == "new"


def test_unknown_session_cannot_poison_shared_memory(installed):
    result = invoke(
        installed, "codex", "unknown", "UserPromptSubmit", prompt="Injected goal", turn_id="bad"
    )
    assert result.returncode == 0
    assert "deferred" in result.stderr
    new = invoke(installed, "codex", "good", "SessionStart", source="startup")
    assert "Injected goal" not in new.stdout


@pytest.mark.parametrize("host", ["codex", "claude-code"])
@pytest.mark.parametrize("turn_id", ["same-turn", None])
def test_steering_prompts_have_distinct_receipts_and_retries_are_idempotent(
    installed, host, turn_id
):
    from neurath.memory.store import ProjectMemory

    assert invoke(installed, host, "steering", "SessionStart", source="startup").returncode == 0
    for prompt in (
        "Initial request",
        "Additional request",
        "Additional request",
        "Initial request",
    ):
        result = invoke(
            installed, host, "steering", "UserPromptSubmit", prompt=prompt, turn_id=turn_id
        )
        assert result.returncode == 0, result.stderr
    prompts = [
        row for row in ProjectMemory(installed).history(host, "steering") if row["kind"] == "prompt"
    ]
    assert [row["content"] for row in prompts] == [
        "Initial request",
        "Additional request",
        "Initial request",
    ]

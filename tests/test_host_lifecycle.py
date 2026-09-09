"""Host protocol regression tests; payloads here are simulated, not host proof."""

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


def invoke(root, host, event, **fields):
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("NEURATH_", "CODEX_", "CLAUDE_"))
    }
    return subprocess.run(
        [str(root / ".neurath/run"), "hook", "--host", host],
        input=json.dumps(
            {"cwd": str(root), "session_id": "resume-test", "hook_event_name": event, **fields}
        ),
        text=True,
        capture_output=True,
        env=environment,
        check=False,
    )


def state_snapshot(root):
    from neurath.runtime.engine import activate
    activate(root)
    from scripts.agent_harness.session_kernel import SessionKernel, SessionLocator, SessionId
    return SessionKernel(SessionLocator(root)).inspect(SessionId("resume-test")).to_payload()


def enclave_snapshot(root):
    from neurath.runtime.engine import activate
    activate(root)
    from scripts.agent_harness.session_kernel import SessionLocator, SessionId
    from scripts.agent_harness.enclave_store import EnclaveStore
    return EnclaveStore(SessionLocator(root), max_bytes=4096).read(SessionId("resume-test")).to_payload()


@pytest.mark.parametrize("host", ["codex", "claude-code"])
def test_transport_exit_preserves_resumable_logical_session(installed, host):
    start = invoke(installed, host, "SessionStart", source="startup")
    assert start.returncode == 0, start.stderr
    enclave = enclave_snapshot(installed)
    ended = invoke(installed, host, "SessionEnd", reason="prompt_input_exit")
    assert ended.returncode == 0, ended.stderr
    assert enclave_snapshot(installed) == enclave, "transport exit deleted resumable context"
    assert state_snapshot(installed)["session"]["status"] == "active"
    resumed = invoke(installed, host, "SessionStart", source="resume")
    assert resumed.returncode == 0, resumed.stderr
    assert "neurath-enclave" in resumed.stdout
    prompted = invoke(
        installed, host, "UserPromptSubmit", prompt="Continue after resume", turn_id="resumed-turn"
    )
    assert prompted.returncode == 0, prompted.stderr
    assert "blocked" not in prompted.stdout.lower()


@pytest.mark.parametrize("host", ["codex", "claude-code"])
def test_unknown_session_resume_is_not_reported_as_success(installed, host):
    result = invoke(installed, host, "SessionStart", source="resume")
    assert result.returncode != 0
    from scripts.agent_harness.session_kernel import SessionNotFound
    with pytest.raises(SessionNotFound):
        state_snapshot(installed)


@pytest.mark.parametrize("host", ["codex", "claude-code"])
@pytest.mark.parametrize(
    "tool,inputs",
    [
        (
            "Bash",
            {"command": ".neurath/run engine scripts.agent_harness.state_cli session inspect"},
        ),
        ("Write", {"file_path": "child.txt", "content": "unsafe"}),
    ],
)
def test_child_without_process_identity_cannot_use_parent_authority(installed, host, tool, inputs):
    assert invoke(installed, host, "SessionStart", source="startup").returncode == 0
    before = state_snapshot(installed)
    result = invoke(
        installed, host, "PreToolUse", agent_id="native-child", tool_name=tool, tool_input=inputs
    )
    assert result.returncode != 0, (
        "unbound child was allowed to execute with inherited root identity"
    )
    assert "child" in result.stderr.lower()
    assert state_snapshot(installed) == before


@pytest.mark.parametrize("host", ["codex", "claude-code"])
def test_unattested_child_is_not_given_a_claimed_runtime_binding(installed, host):
    assert invoke(installed, host, "SessionStart", source="startup").returncode == 0
    result = invoke(
        installed,
        host,
        "SubagentStart",
        agent_id="native-child",
        agent_type="default",
        turn_id="child-turn",
    )
    assert result.returncode == 0
    assert "pending" in result.stdout
    assert "neurath-runtime-binding" not in result.stdout


@pytest.mark.parametrize("host", ["codex", "claude-code"])
def test_explicitly_retired_session_is_never_revived(installed, host):
    import sys

    assert invoke(installed, host, "SessionStart", source="startup").returncode == 0
    script = """
import sys
from pathlib import Path
from neurath.runtime.engine import activate
activate(Path(sys.argv[1]))
from scripts.agent_harness.session_kernel import SessionLocator, SessionKernel, SessionEnded, SessionId, ActorId
SessionKernel(SessionLocator.from_worktree(Path(sys.argv[1]))).apply(SessionEnded(session_id=SessionId('resume-test'), actor_id=ActorId(sys.argv[2]+':session:resume-test'), idempotency_key='explicit-retirement'))
"""
    subprocess.run([sys.executable, "-I", "-c", script, str(installed), host], check=True)
    before = state_snapshot(installed)
    assert invoke(installed, host, "SessionStart", source="resume").returncode != 0
    assert state_snapshot(installed) == before

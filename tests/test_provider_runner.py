"""Exercise CLI subprocess outcomes, cancellation and provider/session selection."""

import json
import os
import subprocess
import threading
import time

import pytest

from neurath.agents import runner
from neurath.agents.store import AgentIdentity, MessageStore


@pytest.fixture
def worker(tmp_path, monkeypatch):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    store = MessageStore(tmp_path)
    owner = AgentIdentity("codex", "parent", "parent-root")
    store.register(owner)

    def executable(source):
        import sys

        script = tmp_path / "fake-provider"
        script.write_text(f"#!{sys.executable}\n" + source)
        script.chmod(0o700)
        monkeypatch.setattr(runner.shutil, "which", lambda name: str(script))

    return store, owner.address, executable


@pytest.mark.parametrize("provider", ["codex", "claude-code"])
def test_provider_runs_with_selected_model_and_structured_result(worker, provider):
    store, owner, executable = worker
    if provider == "codex":
        output = "\n".join(
            json.dumps(x)
            for x in [
                {"type": "thread.started", "thread_id": "native-worker"},
                {"type": "item.completed", "item": {"type": "agent_message", "text": "Reviewed"}},
                {"type": "turn.completed", "usage": {"input_tokens": 2, "output_tokens": 1}},
            ]
        )
    else:
        output = json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "session_id": "native-worker",
                "result": "Reviewed",
                "usage": {"input_tokens": 2},
            }
        )
    executable(
        "import sys\nassert '--model' in sys.argv\nassert 'chosen-model' in sys.argv\n"
        "assert 'Task' in sys.stdin.read()\nprint(" + repr(output) + ")\n"
    )
    result = runner.run(store, owner, provider=provider, model="chosen-model", assignment="Task")
    assert result["status"] == "completed"
    assert result["text"] == "Reviewed"
    assert result["native_session"] == "native-worker"
    assert result["authority"] == "agent-report"
    assert runner.status(store, owner, result["run_id"])["result"] == result


def test_failure_inside_successful_cli_process_is_not_success(worker):
    store, owner, executable = worker
    executable(
        'print(\'{"type":"result","is_error":true,"subtype":"error_max_turns","result":"Failed"}\')\n'
    )
    result = runner.run(store, owner, provider="claude-code", model="m", assignment="Task")
    assert result["status"] == "failed"
    assert result["exit_code"] == 0


def test_missing_terminal_event_is_not_success(worker):
    store, owner, executable = worker
    executable('print(\'{"type":"thread.started","thread_id":"partial"}\')\n')
    result = runner.run(store, owner, provider="codex", model="m", assignment="Task")
    assert result["status"] == "failed"


def test_claude_error_with_success_subtype_keeps_real_diagnostic():
    result = runner.parse_result(
        "claude-code",
        json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "is_error": True,
                "result": "CLI version is too old for this model",
            }
        ),
    )
    assert not result["provider_success"]
    assert result["provider_error"] == "CLI version is too old for this model"
    assert result["actual_model"] is None


def test_nonzero_exit_overrides_terminal_success(worker):
    store, owner, executable = worker
    executable(
        'import sys\nprint(\'{"type":"result","is_error":false,"subtype":"success","result":"Looks fine"}\')\nsys.exit(9)\n'
    )
    result = runner.run(store, owner, provider="claude-code", model="m", assignment="Task")
    assert result["status"] == "failed"
    assert result["exit_code"] == 9


def test_successful_resume_with_wrong_session_is_rejected(worker):
    store, owner, executable = worker
    executable(
        'print(\'{"type":"result","is_error":false,"subtype":"success","session_id":"first","result":"OK"}\')\n'
    )
    first = runner.run(store, owner, provider="claude-code", model="m", assignment="Task")
    executable(
        'print(\'{"type":"result","is_error":false,"subtype":"success","session_id":"other","result":"OK"}\')\n'
    )
    result = runner.resume(store, owner, first["run_id"], "Followup")
    assert result["status"] == "failed"
    assert "different" in result["provider_error"]


def test_timeout_preserves_failure_and_cleans_up(worker):
    store, owner, executable = worker
    executable("import time\ntime.sleep(10)\n")
    started = time.monotonic()
    result = runner.run(store, owner, provider="codex", model="m", assignment="Task", timeout=0.1)
    assert result["status"] == "timed-out"
    assert time.monotonic() - started < 4


def test_cancellation_is_owner_scoped_and_observed_by_running_process(worker):
    store, owner, executable = worker
    executable("import time\ntime.sleep(10)\n")
    result = []
    thread = threading.Thread(
        target=lambda: result.append(
            runner.run(
                store, owner, provider="codex", model="m", assignment="Task", run_id="cancel-me"
            )
        )
    )
    thread.start()
    try:
        for _ in range(100):
            try:
                if runner.status(store, owner, "cancel-me")["status"] == "running":
                    break
            except ValueError:
                pass
            time.sleep(0.02)
        with pytest.raises(ValueError, match="owner"):
            runner.cancel(store, "another-agent", "cancel-me")
        runner.cancel(store, owner, "cancel-me")
        thread.join(4)
        assert not thread.is_alive()
        assert result[0]["status"] == "cancelled"
    finally:
        thread.join(12)


def test_resume_uses_owned_exact_session_and_retains_provider(worker):
    store, owner, executable = worker
    output = json.dumps(
        {
            "type": "result",
            "is_error": False,
            "subtype": "success",
            "session_id": "owned-session",
            "result": "First",
        }
    )
    executable("print(" + repr(output) + ")\n")
    first = runner.run(store, owner, provider="claude-code", model="fable-model", assignment="Task")
    executable(
        "import sys\nassert '--resume' in sys.argv\nassert 'owned-session' in sys.argv\n"
        "assert 'fable-model' in sys.argv\nprint(" + repr(output) + ")\n"
    )
    second = runner.resume(store, owner, first["run_id"], "Follow up")
    assert second["status"] == "completed"
    with pytest.raises(ValueError, match="owner"):
        runner.resume(store, "other", first["run_id"], "Hijack")


def test_child_environment_keeps_auth_but_not_parent_authority():
    env = runner.child_environment(
        {
            "CODEX_HOME": "/configured",
            "ANTHROPIC_API_KEY": "secret",
            "CODEX_THREAD_ID": "parent",
            "CODEX_APP_TOOLS_PIPE_PATH": "/parent/tool-control",
            "CODEX_ACTOR_ID": "parent-actor",
            "CLAUDE_CODE_SESSION_ID": "parent",
            "CLAUDECODE": "1",
            "CLAUDE_CODE_MESSAGING_SOCKET": "/parent/socket",
            "CLAUDE_CODE_MESSAGING_TOKEN": "parent-peer-authority",
            "NEURATH_TOOL_BINDING": "parent-receipt",
            "NEURATH_TARGET_ROOT": "/parent",
            "PYTHONPATH": "/injected",
            "PATH": os.defpath,
        }
    )
    assert env["CODEX_HOME"] == "/configured"
    assert env["ANTHROPIC_API_KEY"] == "secret"
    assert not any(
        k in env for k in ("CODEX_THREAD_ID", "CLAUDE_CODE_SESSION_ID", "CLAUDECODE", "PYTHONPATH")
    )
    assert not any(k.startswith("NEURATH_") for k in env)
    assert "CLAUDE_CODE_MESSAGING_SOCKET" not in env
    assert "CLAUDE_CODE_MESSAGING_TOKEN" not in env
    assert "CODEX_APP_TOOLS_PIPE_PATH" not in env
    assert "CODEX_ACTOR_ID" not in env


def test_claude_init_retains_observed_mode_and_model():
    output = '\n'.join(json.dumps(event) for event in [
        {"type": "system", "subtype": "init", "session_id": "session", "cwd": "/work",
         "model": "selected", "permissionMode": "dontAsk", "tools": ["Read"]},
        {"type": "result", "session_id": "session", "is_error": False,
         "subtype": "success", "result": "Done"},
    ])
    result = runner.parse_result("claude-code", output)
    assert result["effective_settings"]["approval_policy"] == "dontAsk"
    assert result["effective_settings"]["model"] == "selected"
    assert result["effective_settings"]["worktree"] == "/work"


def test_command_rejects_unknown_provider_instead_of_running_claude(worker):
    with pytest.raises(ValueError, match="unsupported provider"):
        runner.command("typo", "chosen")


def test_unavailable_provider_does_not_fall_back(worker, monkeypatch):
    store, owner, _ = worker
    monkeypatch.setattr(runner.shutil, "which", lambda name: None)
    with pytest.raises(ValueError, match="installed"):
        runner.run(store, owner, provider="claude-code", model="specific", assignment="Task")


def test_write_mode_requires_a_separate_installed_worktree(worker):
    store, owner, _ = worker
    with pytest.raises(ValueError, match="worktree"):
        runner.run(
            store, owner, provider="codex", model="m", assignment="Task", mode="workspace-write"
        )


def test_cli_write_assignment_is_not_dispatched_without_native_readiness(worker, monkeypatch):
    from neurath.providers.contracts import UnsupportedOperation
    store, owner, _ = worker
    monkeypatch.setattr(runner, "_workspace", lambda *_: store.worktree)
    def forbidden(*args, **kwargs):
        pytest.fail("provider process was dispatched before readiness")
    monkeypatch.setattr(runner, "command", forbidden)
    with pytest.raises(UnsupportedOperation, match="readiness"):
        runner.run(store, owner, provider="codex", model="m", assignment="Implement", mode="workspace-write")
    with store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0


def test_effective_claude_model_mismatch_is_visible(worker):
    store, owner, executable = worker
    events = [
        {"type": "system", "subtype": "init", "cwd": str(store.worktree),
         "model": "other", "permissionMode": "dontAsk", "session_id": "native"},
        {"type": "result", "subtype": "success", "session_id": "native", "result": "OK"},
    ]
    executable("print(" + repr("\n".join(json.dumps(event) for event in events)) + ")\n")
    result = runner.run(store, owner, provider="claude-code", model="chosen", assignment="Read")
    assert result["status"] == "failed"
    assert result["execution_policy"]["verification"] == "mismatch"
    assert result["execution_policy"]["effective"]["model"] == "other"

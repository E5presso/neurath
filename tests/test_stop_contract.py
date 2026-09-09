"""Normal Stop preserves unfinished work and cannot waive kernel completion."""

import json
import subprocess

import pytest

from neurath.hosts.hooks import hook
from neurath.install.transaction import apply_plan, make_plan
from neurath.runtime.engine import activate


@pytest.fixture
def stop_runtime(tmp_path, monkeypatch):
    from neurath.hosts import identity

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    apply_plan(tmp_path, make_plan(tmp_path))
    activate(tmp_path)
    storage = tmp_path / "host"
    storage.mkdir()
    monkeypatch.setattr(identity, "host_storage", lambda *_: storage)
    transcript = storage / "root.jsonl"
    def send(host, event, **fields):
        if not transcript.exists():
            records = ([{"type": "session_meta", "payload": {
                "id": "root", "source": "vscode", "thread_source": "user", "cwd": str(tmp_path),
            }}, {"type": "event_msg", "payload": {"type": "task_started", "turn_id": "turn-1"}}]
                       if host == "codex" else [{"type": "user", "sessionId": "root",
                           "cwd": str(tmp_path), "message": {"role": "user", "content": "Start work"}}])
            transcript.write_text("".join(json.dumps(record) + "\n" for record in records))
        native_turn = {"turn_id": "turn-1"} if host == "codex" else {}
        if host == "claude-code":
            fields.pop("turn_id", None)
        return hook(tmp_path, host, json.dumps({
            "hook_event_name": event, "session_id": "root", "cwd": str(tmp_path),
            "transcript_path": str(transcript), **native_turn, **fields,
        }), {})

    return tmp_path, send


@pytest.mark.parametrize("host", ["codex", "claude-code"])
def test_repeated_handoff_request_keeps_blocking_without_completing(stop_runtime, monkeypatch, host):
    from neurath.memory import hooks as memory
    from scripts.agent_harness.session_kernel import SessionId, SessionKernel, SessionLocator

    root, send = stop_runtime
    assert send(host, "SessionStart", source="startup")[0] == 0
    assert send(host, "UserPromptSubmit", prompt="Complete the requested work")[0] == 0
    monkeypatch.setattr(memory, "checkpoint_request", lambda *_: "Save the missing handoff")
    kernel = SessionKernel(SessionLocator.from_worktree(root))
    before = kernel.inspect(SessionId("root")).to_payload()
    code, output, _ = send(host, "Stop", stop_hook_active=False)
    assert code == 0 and output.get("decision") == "block"
    assert output.get("reason") == "Save the missing handoff"
    # Neither continuation flags nor duplicate events waive unfinished work.
    for active in (True, False, True):
        code, output, diagnostic = send(host, "Stop", stop_hook_active=active)
        assert code == 0 and output.get("decision") == "block", diagnostic
        assert output.get("continue") is not False
        assert kernel.inspect(SessionId("root")).to_payload() == before


@pytest.mark.parametrize("host", ["codex", "claude-code"])
def test_missing_session_stop_is_nonblocking_and_creates_no_state(stop_runtime, host):
    root, send = stop_runtime
    for active in (False, True):
        code, output, diagnostic = send(host, "Stop", stop_hook_active=active)
        assert code == 1 and "decision" not in output, diagnostic
    from scripts.agent_harness.session_kernel import SessionStateStore, SessionLocator, SessionId
    assert not SessionStateStore(SessionLocator(root).locate(SessionId("root")).process_state).exists()


@pytest.mark.parametrize("host", ["codex", "claude-code"])
def test_retry_can_finish_once_prerequisite_is_met(stop_runtime, monkeypatch, host):
    from neurath.memory import hooks as memory
    from scripts.agent_harness.session_kernel import SessionId, SessionKernel, SessionLocator

    root, send = stop_runtime
    assert send(host, "SessionStart", source="startup")[0] == 0
    assert send(host, "UserPromptSubmit", prompt="Finish after recording results")[0] == 0
    monkeypatch.setattr(memory, "checkpoint_request", lambda *_: "Save handoff")
    assert send(host, "Stop", stop_hook_active=False)[1].get("decision") == "block"
    monkeypatch.setattr(memory, "checkpoint_request", lambda *_: None)
    code, output, diagnostic = send(host, "Stop", stop_hook_active=True)
    assert code == 0 and not output.get("decision"), diagnostic
    state = SessionKernel(SessionLocator.from_worktree(root)).inspect(SessionId("root"))
    assert state.foreground_turns[state.session.root_actor_id].status.value == "closed"


@pytest.mark.parametrize("host", ["codex", "claude-code"])
def test_unfinished_work_keeps_blocking_across_user_turns(
    stop_runtime, monkeypatch, host,
):
    from neurath.memory import hooks as memory
    from scripts.agent_harness import session_kernel as k

    root, send = stop_runtime
    assert send(host, "SessionStart", source="startup")[0] == 0
    assert send(host, "UserPromptSubmit", prompt="Implement the whole request")[0] == 0
    monkeypatch.setattr(memory, "checkpoint_request", lambda *_: None)
    kernel = k.SessionKernel(k.SessionLocator.from_worktree(root))
    state = kernel.inspect(k.SessionId("root"))
    from scripts.agent_harness.state_handle import StateHandle, RuntimeIdentityBinding
    from scripts.agent_harness.task_service import TaskService
    handle = StateHandle.attach(k.SessionLocator.from_worktree(root), RuntimeIdentityBinding(
        runtime=state.session.runtime, session_id=state.session.id,
        actor_id=state.session.root_actor_id, root_actor_id=state.session.root_actor_id))
    TaskService(handle).define([{"key": "whole-request", "title": "Complete the whole request",
        "goal": "Complete all acceptance criteria", "sources": [],
        "acceptance": ["All requested behavior is complete"], "evidence_contract": "unfinished",
        "dependencies": []}], expected_revision=0, key="define-whole-request")
    kernel.apply(k.WorkflowStarted(
        session_id=state.session.id, workflow_id=k.WorkflowId("unfinished"),
        owner_actor_id=state.session.root_actor_id, kind="checkpoint",
        goal="Complete all acceptance criteria", payload={}, idempotency_key="unfinished",
    ))
    assert send(host, "Stop", stop_hook_active=False)[1].get("decision") == "block"
    assert send(host, "Stop", stop_hook_active=True)[1].get("decision") == "block"
    state = kernel.inspect(k.SessionId("root"))
    assert state.workflows[k.WorkflowId("unfinished")].status.value == "active"
    assert state.foreground_turns[state.session.root_actor_id].status.value == "active"
    transcript = root / "host/root.jsonl"
    if host == "codex":
        with transcript.open("a") as stream:
            stream.write(json.dumps({"type": "event_msg", "payload": {
                "type": "task_started", "turn_id": "turn-2",
            }}) + "\n")
    assert send(host, "SessionStart", source="resume")[0] == 0
    assert send(host, "UserPromptSubmit", turn_id="turn-2", prompt="Continue the same work")[0] == 0
    code, output, diagnostic = send(host, "Stop", turn_id="turn-2", stop_hook_active=False)
    assert code == 0 and output.get("decision") == "block", diagnostic
    assert kernel.inspect(k.SessionId("root")).workflows[k.WorkflowId("unfinished")].status.value == "active"


@pytest.mark.parametrize("host", ["codex", "claude-code"])
def test_stop_infrastructure_failure_never_reenters_or_completes(stop_runtime, monkeypatch, host):
    from neurath.hosts import hooks
    from neurath.memory import hooks as memory
    from scripts.agent_harness import session_kernel as k

    root, send = stop_runtime
    assert send(host, "SessionStart", source="startup")[0] == 0
    assert send(host, "UserPromptSubmit", prompt="Preserve pending work")[0] == 0
    monkeypatch.setattr(memory, "checkpoint_request", lambda *_: None)
    kernel = k.SessionKernel(k.SessionLocator.from_worktree(root))
    before = kernel.inspect(k.SessionId("root")).to_payload()

    def unavailable(*_):
        raise RuntimeError("unavailable host state service")

    monkeypatch.setattr(hooks, "_host_hook", unavailable)
    for active in (False, True, False):
        code, output, diagnostic = send(host, "Stop", stop_hook_active=active)
        assert code == 1 and output == {}, diagnostic
        assert "unavailable host state service" in diagnostic
        assert kernel.inspect(k.SessionId("root")).to_payload() == before


@pytest.mark.parametrize("event", ["UserPromptSubmit", "SessionEnd"])
@pytest.mark.parametrize("pending", [False, True])
def test_claude_lifecycle_change_during_stop_preserves_new_state(
    stop_runtime, monkeypatch, event, pending,
):
    from neurath.memory import hooks as memory
    from scripts.agent_harness import session_kernel as k

    root, send = stop_runtime
    host = "claude-code"
    assert send(host, "SessionStart", source="startup")[0] == 0
    assert send(host, "UserPromptSubmit", prompt="Initial request")[0] == 0
    kernel = k.SessionKernel(k.SessionLocator.from_worktree(root))
    observed = []

    def raced_checkpoint(*_):
        fields = {"prompt": "New user instruction"} if event == "UserPromptSubmit" else {}
        assert send(host, event, **fields)[0] == 0
        observed.append(kernel.inspect(k.SessionId("root")).to_payload())
        return "Handoff remains pending" if pending else None

    monkeypatch.setattr(memory, "checkpoint_request", raced_checkpoint)
    code, output, diagnostic = send(host, "Stop", stop_hook_active=False)
    assert code in (0, 1) and output.get("decision") != "block", diagnostic
    assert kernel.inspect(k.SessionId("root")).to_payload() == observed[-1]
    from neurath.hosts.identity import snapshot
    assert snapshot(root, "root").get("stop_continuation") is None


def test_external_stop_readback_never_holds_up_human_input(stop_runtime, monkeypatch):
    import threading
    from neurath.memory import hooks as memory
    from scripts.agent_harness.agent_continuation_hook import AgentContinuationHookApplication
    from scripts.agent_harness import session_kernel as k

    root, send = stop_runtime
    assert send("claude-code", "SessionStart", source="startup")[0] == 0
    assert send("claude-code", "UserPromptSubmit", prompt="Original request")[0] == 0
    monkeypatch.setattr(memory, "checkpoint_request", lambda *_: None)
    delivered = threading.Event()
    result = []

    def user_input():
        result.append(send("claude-code", "UserPromptSubmit", prompt="New human correction"))
        delivered.set()

    worker = threading.Thread(target=user_input, daemon=True)

    def external_readback(*_):
        worker.start()
        if not delivered.wait(2):
            raise RuntimeError("human prompt waited on external Stop validation")

    monkeypatch.setattr(AgentContinuationHookApplication, "_validate_monitor_workflows", external_readback)
    _, output, diagnostic = send("claude-code", "Stop", stop_hook_active=False)
    worker.join(timeout=5)
    assert delivered.is_set() and result[0][0] == 0
    assert "human prompt waited" not in diagnostic
    assert output.get("decision") != "block"
    state = k.SessionKernel(k.SessionLocator.from_worktree(root)).inspect(k.SessionId("root"))
    assert state.foreground_turns[state.session.root_actor_id].status.value == "active"


@pytest.mark.parametrize("host", ["codex", "claude-code"])
def test_yielded_turn_with_pending_task_still_emits_blocking_stop(stop_runtime, monkeypatch, host):
    from neurath.memory import hooks as memory
    from scripts.agent_harness import session_kernel as k
    from scripts.agent_harness.state_handle import StateHandle, RuntimeIdentityBinding
    from scripts.agent_harness.task_service import TaskService
    root, send = stop_runtime
    assert send(host, "SessionStart", source="startup")[0] == 0
    assert send(host, "UserPromptSubmit", prompt="Finish the original request")[0] == 0
    monkeypatch.setattr(memory, "checkpoint_request", lambda *_: None)
    locator = k.SessionLocator.from_worktree(root)
    kernel = k.SessionKernel(locator)
    state = kernel.inspect(k.SessionId("root"))
    handle = StateHandle.attach(locator, RuntimeIdentityBinding(runtime=state.session.runtime,
        session_id=state.session.id, actor_id=state.session.root_actor_id,
        root_actor_id=state.session.root_actor_id))
    tasks = TaskService(handle)
    tasks.define([{"key": "original", "title": "Original request", "goal": "Finish original request",
        "sources": [], "acceptance": ["All required behavior is implemented"],
        "evidence_contract": "future-work", "dependencies": []}], expected_revision=0, key="define-original")
    turn = kernel.inspect(state.session.id).foreground_turns[state.session.root_actor_id]
    kernel.apply(k.ForegroundTurnYielded(session_id=state.session.id, actor_id=state.session.root_actor_id,
        expected_turn_revision=turn.revision,
        receipt=k.ForegroundTurnReceipt(k.ForegroundTurnOutcome.COMPLETED, summary="Answered only the side question"),
        idempotency_key="yield-side-answer"))
    for active in (False, True):
        code, reply, diagnostic = send(host, "Stop", stop_hook_active=active)
        assert code == 0 and reply.get("decision") == "block", diagnostic
    assert tasks.list()["tasks"][0]["status"] == "pending"
    assert kernel.inspect(state.session.id).foreground_turns[state.session.root_actor_id].status is k.ForegroundTurnStatus.ACTIVE

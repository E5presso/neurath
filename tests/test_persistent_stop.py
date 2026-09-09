"""A side question or continuation flag cannot complete outstanding work."""
from neurath.memory import hooks as memory

pytest_plugins = ["tests.test_stop_contract"]


def _pending(stop_runtime, monkeypatch, host):
    from scripts.agent_harness import session_kernel as k
    root, send = stop_runtime
    assert send(host, "SessionStart", source="startup")[0] == 0
    assert send(host, "UserPromptSubmit", prompt="Implement the original request")[0] == 0
    monkeypatch.setattr(memory, "checkpoint_request", lambda *_: None)
    kernel = k.SessionKernel(k.SessionLocator.from_worktree(root))
    state = kernel.inspect(k.SessionId("root"))
    kernel.apply(k.WorkflowStarted(
        session_id=state.session.id, workflow_id=k.WorkflowId("original-work"),
        owner_actor_id=state.session.root_actor_id, kind="checkpoint",
        goal="Implement the original request", payload={}, idempotency_key="original-work"))
    return send, kernel


def test_codex_repeated_stop_cannot_abandon_original_work(stop_runtime, monkeypatch):
    from scripts.agent_harness import session_kernel as k
    send, kernel = _pending(stop_runtime, monkeypatch, "codex")
    for active in (False, True, False, True):
        code, result, diagnostic = send("codex", "Stop", stop_hook_active=active)
        assert code == 0 and result.get("decision") == "block", diagnostic
        assert result.get("continue") is not False
    state = kernel.inspect(k.SessionId("root"))
    assert state.workflows[k.WorkflowId("original-work")].status.value == "active"


def test_claude_side_question_preserves_stop_obligation(stop_runtime, monkeypatch):
    from scripts.agent_harness import session_kernel as k
    send, kernel = _pending(stop_runtime, monkeypatch, "claude-code")
    assert send("claude-code", "Stop", stop_hook_active=False)[1].get("decision") == "block"
    assert send("claude-code", "UserPromptSubmit", prompt="Explain the model tool; this is a side question")[0] == 0
    for active in (True, False, True):
        code, result, diagnostic = send("claude-code", "Stop", stop_hook_active=active)
        assert code == 0 and result.get("decision") == "block", diagnostic
    state = kernel.inspect(k.SessionId("root"))
    assert state.workflows[k.WorkflowId("original-work")].goal == "Implement the original request"

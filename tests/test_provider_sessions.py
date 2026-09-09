"""Session transports preserve host identity, applied policy and live-turn semantics."""

import pytest

from neurath.providers.codex import CodexSessions
from neurath.providers.contracts import ExecutionPolicy, UnsupportedOperation
from neurath.providers.catalog import capabilities


class Host:
    def __init__(self):
        self.calls = []
        self.thread = {"id": "native-id", "projectId": "saved", "cwd": "/work", "status": {"type": "idle"}, "turns": []}
        self.approval = "never"
        self.sandbox = {"type": "readOnly", "networkAccess": False}
        self.model = "chosen-model"

    def request(self, method, params):
        self.calls.append((method, params))
        if method == "project/list":
            return {"data": [{"id": "saved", "roots": [{"path": "/work"}]}]}
        if method in ("thread/start", "thread/resume"):
            return {"thread": self.thread.copy(), "model": self.model, "cwd": "/work",
                    "approvalPolicy": self.approval, "sandbox": self.sandbox}
        if method == "thread/read":
            return {"thread": self.thread.copy()}
        if method == "turn/start":
            return {"turn": {"id": "turn-id", "status": "inProgress"}}
        if method == "turn/steer":
            return {"turnId": params["expectedTurnId"]}
        if method == "thread/list":
            return {"data": [self.thread.copy()], "nextCursor": None}
        return {}


def test_create_verifies_effective_policy_before_any_prompt():
    host = Host()
    session = CodexSessions(host).create("/work", "chosen-model", ExecutionPolicy())
    assert session.native_session == "native-id"
    assert session.policy["verification"] == "verified"
    assert host.calls[0][0] == "thread/start"
    assert host.calls[0][1]["approvalPolicy"] == "never"
    assert host.calls[0][1]["sandbox"] == "read-only"
    assert all(method != "turn/start" for method, _ in host.calls)


@pytest.mark.parametrize("field,value", [("approval", "on-request"), ("sandbox", {"type": "dangerFullAccess"})])
def test_policy_mismatch_cannot_start_assignment(field, value):
    host = Host()
    setattr(host, field, value)
    adapter = CodexSessions(host)
    with pytest.raises(ValueError, match="policy"):
        adapter.create("/work", "chosen-model", ExecutionPolicy())
    assert all(method != "turn/start" for method, _ in host.calls)


def test_live_message_steers_exact_turn_without_resume():
    host = Host()
    adapter = CodexSessions(host)
    session = adapter.create("/work", "chosen-model", ExecutionPolicy())
    host.thread.update(status={"type": "active"}, turns=[{"id": "live", "status": "inProgress"}])
    result = adapter.message(session, "peer request")
    assert result["delivery"] == "submitted"
    assert host.calls[-1] == ("turn/steer", {"threadId": "native-id", "expectedTurnId": "live",
                                           "input": [{"type": "text", "text": "peer request"}]})
    assert all(method != "thread/resume" for method, _ in host.calls)


def test_waiting_for_approval_is_reported_without_steer_or_resume():
    host = Host()
    adapter = CodexSessions(host)
    session = adapter.create("/work", "chosen-model", ExecutionPolicy())
    host.thread.update(status={"type": "active", "activeFlags": ["waitingOnApproval"]},
                       turns=[{"id": "live", "status": "inProgress"}])
    assert adapter.message(session, "continue")["delivery"] == "needs-input"
    assert host.calls[-1][0] == "thread/read"


def test_cancel_is_exact_turn_interrupt_and_cannot_control_foreign_session():
    host = Host()
    adapter = CodexSessions(host)
    session = adapter.create("/work", "chosen-model", ExecutionPolicy())
    host.thread.update(status={"type": "active"}, turns=[{"id": "live", "status": "inProgress"}])
    adapter.cancel(session)
    assert host.calls[-1] == ("turn/interrupt", {"threadId": "native-id", "turnId": "live"})
    with pytest.raises(ValueError, match="owned"):
        CodexSessions(host).cancel(session)


def test_catalog_does_not_infer_native_tools_from_version_or_desktop_install():
    rows = capabilities("claude-code", available_tools=())
    native = next(row for row in rows if row["transport"] == "claude-native")
    assert native["operations"]["message"]["available"] is False
    rows = capabilities("claude-code", available_tools=("ListAgents", "SendMessage"))
    native = next(row for row in rows if row["transport"] == "claude-native")
    assert native["operations"]["message"]["available"] is True
    assert native["operations"]["create"]["available"] is False
    with pytest.raises(UnsupportedOperation):
        capabilities("unknown")


@pytest.mark.parametrize("field,value", [
    ("model", "other-model"), ("model", None),
    ("sandbox", {"type": "readOnly", "networkAccess": True}),
    ("sandbox", {"type": "readOnly"}),
])
def test_mismatch_preserves_created_handle_without_granting_prompt_control(field, value):
    from neurath.providers.contracts import CreationRejected
    host = Host()
    setattr(host, field, value)
    adapter = CodexSessions(host)
    with pytest.raises(CreationRejected) as caught:
        adapter.create("/work", "chosen-model")
    session = caught.value.session
    assert session.native_session == "native-id"
    assert session.policy["verification"] == "mismatch"
    assert caught.value.report["prompt_submitted"] is False
    with pytest.raises(ValueError, match="owned"):
        adapter.message(session, "assignment")
    assert [name for name, _ in host.calls] == ["thread/start"]


def test_unsupported_interactive_policy_rejects_before_creating_host_session():
    host = Host()
    with pytest.raises(UnsupportedOperation, match="approval"):
        CodexSessions(host).create("/work", "chosen-model", ExecutionPolicy(approval="on-request"))
    assert host.calls == []


def test_write_assignment_requires_child_native_readiness(monkeypatch):
    from neurath.providers import readiness
    host = Host()
    monkeypatch.setattr(CodexSessions, "_state_roots", staticmethod(lambda _: []))
    host.sandbox = {"type": "workspaceWrite", "networkAccess": False, "writableRoots": []}
    adapter = CodexSessions(host)
    session = adapter.create("/work", "chosen-model", ExecutionPolicy("workspace-write"))
    host.thread.update(status={"type": "active"}, turns=[{"id": "live", "status": "inProgress"}])
    observed = []
    def inspect(handle):
        observed.append(handle.native_session)
        return {"implementation_ready": False, "stages": {"activation": {"status": "failed"}}}
    monkeypatch.setattr(readiness, "inspect_owned_session", inspect)
    with pytest.raises(readiness.SessionNotReady):
        adapter.message(session, "implement feature")
    assert observed == [session.native_session]
    assert all(name != "turn/start" for name, _ in host.calls)


def test_catalog_implementation_does_not_prove_installed_runtime():
    rows = capabilities("codex")
    server = next(row for row in rows if row["transport"] == "codex-app-server")
    assert server["operations"]["create"]["implemented"] is True
    assert server["operations"]["create"]["available"] is False


def test_paginated_host_uses_metadata_and_exact_observed_turn_without_full_hydration():
    host = Host()
    adapter = CodexSessions(host)
    session = adapter.create("/work", "chosen-model")
    adapter.message(session, "first")
    host.thread.update(status={"type": "active"}, turns=[])
    adapter.message(session, "followup")
    assert host.calls[-1][1]["expectedTurnId"] == "turn-id"
    assert all(params["includeTurns"] is False for name, params in host.calls if name == "thread/read")


def test_claude_forward_requires_native_discovery_without_fabricating_recipient(tmp_path):
    import subprocess
    from neurath.agents.store import AgentIdentity, MessageStore
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    store = MessageStore(tmp_path)
    sender = AgentIdentity("codex", "sender", "sender-root")
    target = AgentIdentity("claude-code", "native-uuid", "target-root")
    store.register(sender)
    store.register(target, name="possibly-duplicate")
    message = store.send(sender.address, target.address, "Review", key="review")
    forwarded = store.forward(sender.address, message["id"])
    assert forwarded["status"] == "discovery-required"
    assert forwarded["native_session"] == "native-uuid"
    assert forwarded["discovery_tool"] == "ListAgents"
    assert "arguments" not in forwarded


def test_unspecified_model_preserves_host_default():
    host = Host()
    session = CodexSessions(host).create("/work")
    assert "model" not in host.calls[0][1]
    assert session.requested_model is None
    assert session.actual_model == "chosen-model"


def test_collaboration_mode_is_separate_and_not_silently_dropped():
    host = Host()
    with pytest.raises(UnsupportedOperation, match="collaboration"):
        CodexSessions(host).create("/work", policy=ExecutionPolicy(collaboration_mode="plan"))
    assert host.calls == []


def test_shared_state_root_is_minimal_and_applied_before_bootstrap(monkeypatch):
    monkeypatch.setattr(CodexSessions, "_state_roots", staticmethod(lambda _: ["/main/.neurath/local"]))
    host = Host()
    host.sandbox = {"type": "workspaceWrite", "networkAccess": False,
                    "writableRoots": ["/main/.neurath/local"]}
    session = CodexSessions(host).create("/work", policy=ExecutionPolicy("workspace-write"))
    assert host.calls[0][1]["config"] == {
        "sandbox_workspace_write.writable_roots": ["/main/.neurath/local"],
        "sandbox_workspace_write.network_access": False,
        "sandbox_workspace_write.exclude_tmpdir_env_var": False,
        "sandbox_workspace_write.exclude_slash_tmp": False,
    }
    assert session.policy["verification"] == "verified"
    host.sandbox["writableRoots"] = ["/main"]
    with pytest.raises(ValueError, match="mismatch"):
        CodexSessions(host).create("/work", policy=ExecutionPolicy("workspace-write"))


def test_experimental_collaboration_is_applied_to_bootstrap_not_claimed_at_creation():
    host = Host()
    host.supports_collaboration_mode = True
    adapter = CodexSessions(host)
    session = adapter.create("/work", policy=ExecutionPolicy(collaboration_mode="plan"))
    assert session.policy["effective"]["collaboration_mode"] is None
    adapter.bootstrap(session)
    assert host.calls[-1][1]["collaborationMode"] == {
        "mode": "plan", "settings": {"model": "chosen-model", "developer_instructions": None}}


def test_collaboration_turn_preserves_planned_reasoning_in_both_native_fields():
    host = Host()
    host.supports_collaboration_mode = True
    host.sandbox = {"type": "dangerFullAccess"}
    adapter = CodexSessions(host)
    session = adapter.create("/work", policy=ExecutionPolicy(
        "danger-full-access", "never", collaboration_mode="default"))
    session.policy["requested"]["reasoning_effort"] = "high"

    adapter.bootstrap(session)

    method, params = host.calls[-1]
    assert method == "turn/start"
    assert params["effort"] == "high"
    assert params["collaborationMode"] == {
        "mode": "default",
        "settings": {
            "model": "chosen-model",
            "developer_instructions": None,
            "reasoning_effort": "high",
        },
    }
    assert params["sandboxPolicy"] == {"type": "dangerFullAccess"}
    assert session.policy["requested"]["approval_policy"] == "never"


def test_idle_followup_reuses_same_reasoning_and_collaboration_composition():
    host = Host()
    host.supports_collaboration_mode = True
    host.sandbox = {"type": "dangerFullAccess"}
    adapter = CodexSessions(host)
    session = adapter.create("/work", policy=ExecutionPolicy(
        "danger-full-access", "never", collaboration_mode="default"))
    session.policy["requested"]["reasoning_effort"] = "high"
    adapter.bootstrap(session)
    host.thread["status"] = {"type": "idle"}
    host.thread["turns"] = []

    resumed = adapter.resume(session, "Continue the assigned task")
    assert resumed["delivery"] == "preparation-required"
    adapter.bootstrap(session)

    starts = [params for method, params in host.calls if method == "turn/start"]
    assert len(starts) == 2
    for params in starts:
        assert params["effort"] == "high"
        assert params["collaborationMode"]["settings"]["reasoning_effort"] == "high"
        assert params["sandboxPolicy"] == {"type": "dangerFullAccess"}


def test_idle_write_continuation_requires_new_native_preparation_without_sending_assignment(monkeypatch):
    monkeypatch.setattr(CodexSessions, "_state_roots", staticmethod(lambda _: []))
    host = Host()
    host.sandbox = {"type": "workspaceWrite", "writableRoots": [], "networkAccess": False}
    adapter = CodexSessions(host)
    session = adapter.create("/work", policy=ExecutionPolicy("workspace-write"))
    report = adapter.resume(session, "Implement the next task")
    assert report["delivery"] == "preparation-required"
    assert report["next_operation"] == "bootstrap"
    assert all(name != "turn/start" for name, _ in host.calls)
    adapter.bootstrap(session)
    assert host.calls[-1][0] == "turn/start"
    assert "Implement the next task" not in host.calls[-1][1]["input"][0]["text"]

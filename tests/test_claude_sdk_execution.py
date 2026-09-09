"""Worker policy gates; these tests do not attest a live Claude task."""

import asyncio
import json
import sqlite3
import subprocess
import time
from dataclasses import replace

import pytest
from claude_agent_sdk import ResultMessage, SystemMessage

from neurath.agents.store import AgentIdentity
from neurath.memory.store import canonical
from neurath.providers import execution_claude
from neurath.providers.contracts import Session
from tests.test_claude_sdk import wire  # noqa: F401 - shared real SDK wire fixture


@pytest.mark.parametrize("inputs,diagnostic", [
    ({"mode": "workspace-write", "approval_policy": "never", "collaboration_mode": "default"}, "OS sandbox"),
    ({"mode": "read-only"}, "OS sandbox"),
    ({"mode": "native", "permission_mode": "dontAsk", "approval_policy": "never"}, "not Codex approval"),
    ({"mode": "native", "permission_mode": "dontAsk", "approvals_reviewer": "auto_review"}, "not Codex approval"),
    ({"mode": "native", "permission_mode": "dontAsk", "collaboration_mode": "default"}, "not Codex approval"),
    ({"timeout": 60}, "no execution timeout"),
])
def test_unsupported_policy_never_launches_sdk(tmp_path, monkeypatch, inputs, diagnostic):
    def unexpected(*args, **kwargs):
        pytest.fail("unsupported policy launched a provider")

    monkeypatch.setattr(execution_claude, "ClaudeSession", unexpected)
    result = execution_claude.run(tmp_path, worktree=tmp_path, assignment="Task", **inputs)
    assert result["status"] == "unsupported"
    assert diagnostic in result["diagnostic"]
    assert result["implementation_dispatched"] is False


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    instances = []

    class Prepared:
        def __init__(self, root, **options):
            self.session = None
            self.pending_responses = 0
            self.options = options
            self.closed = False
            self.assignments = []
            self.phase = 0
            instances.append(self)

        async def connect(self):
            return {"status": "connected"}

        async def bootstrap(self, *, claim_worktree=False):
            self.claim_requested = claim_worktree
            self.pending_responses += 1
            return {"delivery": "submitted"}

        async def receive_response(self):
            if not self.session:
                self.session = Session("claude-code", "claude-agent-sdk", "observed-native", str(tmp_path),
                    None, "actual-model", {"verification": "verified",
                                           "requested": {"permission_mode": self.options["permission_mode"]}})
            yield SystemMessage("init", {"session_id": "observed-native"})
            self.pending_responses -= 1
            yield ResultMessage("success", 1, 1, False, 1, "observed-native", result="Native response")

        async def confirm_connection(self):
            assert self.pending_responses == 0
            return {"status": "confirmed"}

        async def dispatch(self, text):
            assert self.pending_responses == 0
            self.assignments.append(text)
            self.pending_responses += 1
            return {"delivery": "submitted", "native_session": "observed-native"}

        async def interrupt(self):
            return {"status": "interrupt-requested"}

        async def close(self):
            self.closed = True

        def observed(self):
            return {"native_session": "observed-native"}

    monkeypatch.setattr(execution_claude, "_target", lambda root, worktree, mode: tmp_path)
    monkeypatch.setattr(execution_claude, "ClaudeSession", Prepared)
    class Inbox:
        def __init__(self, adapter):
            self.adapter = adapter

        def start(self):
            return self

        async def raise_if_failed(self):
            pass

        def response_completed(self):
            assert self.adapter.pending_responses == 0

        async def wait_for_obligations(self):
            return bool(self.adapter.pending_responses)

        def close(self):
            pass

        async def aclose(self):
            self.close()

    monkeypatch.setattr(execution_claude, "ClaudeInbox", Inbox)
    monkeypatch.setattr(execution_claude, "_quiescent_readiness", lambda adapter, prepared: execution_claude._readiness(adapter.session))
    return instances


def test_native_policy_unobservable_blocks_assignment(tmp_path, prepared, monkeypatch):
    monkeypatch.setattr(execution_claude, "_readiness", lambda _: {"waiting": None,
        "stages": {"installation": {"status": "verified"}, "activation": {"status": "verified"},
                   "policy": {"status": "unobserved", "reason": "policy-unobservable"}}})
    result = execution_claude.run(tmp_path, worktree=tmp_path, assignment="Private task",
                                 mode="native", permission_mode="plan")
    assert result["status"] == "not-ready"
    assert result["implementation_dispatched"] is False
    assert prepared[0].assignments == [] and prepared[0].closed
    assert prepared[0].options["permission_mode"] == "plan"


def test_verified_gate_drains_assignment_response_after_preparation(tmp_path, prepared, monkeypatch):
    # Synthetic gate coverage only, not evidence the live Claude gate is verified.
    monkeypatch.setattr(execution_claude, "_readiness", lambda _: {"waiting": None,
        "stages": {name: {"status": "verified"} for name in ("installation", "activation", "policy")}})
    result = execution_claude.run(tmp_path, worktree=tmp_path, assignment="Read source",
                                 mode="native", permission_mode="plan")
    assert result["status"] == "completed"
    assert result["implementation_dispatched"] is True
    assert len(prepared[0].assignments) == 1
    assert prepared[0].pending_responses == 0 and prepared[0].closed
    assert result["execution"] == "native-response-completed"


def test_native_write_requires_claim_and_implementation_readiness(tmp_path, prepared, monkeypatch):
    monkeypatch.setattr(execution_claude, "_readiness", lambda _: {"waiting": None,
        "implementation_ready": False,
        "stages": {name: {"status": "verified"} for name in ("installation", "activation", "policy")}})
    result = execution_claude.run(tmp_path, worktree=tmp_path, assignment="Implement",
                                 mode="native", permission_mode="dontAsk")
    assert result["status"] == "not-ready"
    assert prepared[0].claim_requested is True
    assert prepared[0].assignments == []


def test_native_mode_requires_explicit_permission_mode(tmp_path):
    result = execution_claude.run(tmp_path, worktree=tmp_path, assignment="Task", mode="native")
    assert result["status"] == "settings-required"


def test_provider_error_detail_is_local_and_not_sent_to_issuer(tmp_path, monkeypatch, capsys):
    def failed(*args):
        raise ValueError("private diagnostic fixture")
    monkeypatch.setattr(execution_claude, "_target", failed)
    result = execution_claude.run(tmp_path, worktree=tmp_path, assignment="Task",
                                 mode="native", permission_mode="dontAsk")
    assert result["diagnostic"] == "ValueError"
    assert "private diagnostic fixture" not in json.dumps(result)
    assert "ValueError: private diagnostic fixture" in capsys.readouterr().err


def test_inbox_cleanup_error_closes_sdk_and_cannot_report_success(tmp_path, prepared, monkeypatch):
    monkeypatch.setattr(execution_claude, "_readiness", lambda _: {"waiting": None,
        "stages": {name: {"status": "verified"} for name in ("installation", "activation", "policy")}})

    def failed_close(_):
        raise RuntimeError("inbox close failed")

    monkeypatch.setattr(execution_claude.ClaudeInbox, "close", failed_close)
    result = execution_claude.run(tmp_path, worktree=tmp_path, assignment="Read source",
                                 mode="native", permission_mode="plan")
    assert result["status"] == "failed"
    assert prepared[0].closed is True


@pytest.mark.parametrize("phase", [1, 2])
@pytest.mark.parametrize("fields,status", [
    ({"permission_denials": [{"tool_name": "Write"}]}, "waiting-approval"),
    ({"is_error": True}, "failed"),
    ({"is_error": True, "stop_reason": "interrupted"}, "cancelled"),
])
def test_terminal_native_response_does_not_wait_for_outstanding_work(
    tmp_path, prepared, monkeypatch, phase, fields, status,
):
    monkeypatch.setattr(execution_claude, "_readiness", lambda _: {"waiting": None,
        "stages": {name: {"status": "verified"} for name in ("installation", "activation", "policy")}})
    original = execution_claude.ClaudeSession.receive_response

    async def native_response(self):
        self.phase += 1
        async for message in original(self):
            if isinstance(message, ResultMessage) and self.phase == phase:
                message = replace(message, **fields)
            yield message

    async def outstanding_work(self):
        if self.adapter.phase >= phase:
            pytest.fail("terminal native result waited for outstanding work")
        return True

    monkeypatch.setattr(execution_claude.ClaudeSession, "receive_response", native_response)
    monkeypatch.setattr(execution_claude.ClaudeInbox, "wait_for_obligations", outstanding_work)
    result = execution_claude.run(tmp_path, worktree=tmp_path, assignment="Read source",
                                 mode="native", permission_mode="plan")
    assert result["status"] == status
    assert prepared[0].closed is True


@pytest.fixture
def native_policy(tmp_path, monkeypatch):
    monkeypatch.setattr(execution_claude, "control_root", lambda _: tmp_path)
    from neurath.runtime.database import RuntimeDatabase
    path = RuntimeDatabase(tmp_path).path
    identity = AgentIdentity("claude-code", "native-session", "native-actor")
    context = {"host": identity.host, "session": identity.session, "actor": identity.actor,
               "turn": "native-turn", "tool_use_id": "native-tool", "permission_mode": "dontAsk",
               "user_prompt_receipt": {"turn_revision": 1, "prompt_digest": "native-prompt"}}
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE collaboration_calls (root TEXT, host TEXT, session TEXT, actor TEXT, "
                   "is_root INTEGER, turn TEXT, context TEXT, invocation TEXT, expires REAL)")
        db.execute("INSERT INTO collaboration_calls VALUES(?,?,?,?,?,?,?,?,?)", (
            str(tmp_path), identity.host, identity.session, identity.actor, 1, "native-turn",
            json.dumps(context), canonical([identity.host, identity.session, identity.actor, "native-tool"]),
            time.time() + 300))
    return path, identity, context


def test_native_context_read_keeps_hook_evidence_and_does_not_write(tmp_path, native_policy):
    path, identity, context = native_policy
    before = path.read_bytes()
    observed = execution_claude._policy_context(tmp_path, identity, "native-turn")
    assert observed == context
    assert path.read_bytes() == before


@pytest.mark.parametrize("field", ["session", "actor", "turn", "tool_use_id", "user_prompt_receipt"])
def test_native_context_rejects_mismatched_hook_binding(tmp_path, native_policy, field):
    path, identity, context = native_policy
    context.pop(field)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE collaboration_calls SET context=?", (json.dumps(context),))
    with pytest.raises(ValueError, match="binding differs"):
        execution_claude._policy_context(tmp_path, identity, "native-turn")


def test_expired_or_other_turn_context_is_not_reused(tmp_path, native_policy):
    path, identity, _ = native_policy
    assert execution_claude._policy_context(tmp_path, identity, "other-turn") is None
    with sqlite3.connect(path) as db:
        db.execute("UPDATE collaboration_calls SET expires=0")
    assert execution_claude._policy_context(tmp_path, identity, "native-turn") is None


def test_real_socket_message_wakes_idle_existing_sdk_loop_without_model_wait(wire):  # noqa: F811
    from neurath.agents.lifecycle import TaskLifecycle
    from neurath.agents.store import MessageStore
    from neurath.providers.claude_sdk import ClaudeSession

    subprocess.run(["git", "init", "-q", wire.root], check=True)

    async def exercise():
        events = []
        adapter = ClaudeSession(wire.root, permission_mode="dontAsk",
            event_callback=lambda state, detail: events.append((state, detail)))
        inbox = None
        try:
            await adapter.connect()
            await adapter.bootstrap()
            await wire.response()
            [message async for message in adapter.receive_response()]
            store = MessageStore(wire.root)
            own = AgentIdentity("claude-code", wire.native, "fixture-own")
            peer = AgentIdentity("codex", "fixture-peer", "fixture-peer")
            store.register(own)
            store.register(peer)
            TaskLifecycle(store).bind(own.address, peer.address, key="await-peer", transport="peer-assignment")
            inbox = execution_claude.ClaudeInbox(adapter).start()
            waiter = asyncio.create_task(inbox.wait_for_obligations())
            await asyncio.sleep(0)
            assert not waiter.done()
            assert events[-1][0] == "waiting"
            assert events[-1][1]["reason"] == "delegated-work-pending"
            assert events[-1][1]["scope"] == "task-supervision"
            message = store.send(peer.address, own.address, "Private peer result body", key="reply")
            # This bounded wait belongs to the regression test, not the provider.
            async with asyncio.timeout(5):
                assert await waiter is True
            assert adapter.pending_responses == 1
            prompt = [item["message"]["content"] for item in wire.writes if item["type"] == "user"][-1]
            assert message["id"] in prompt
            assert "Private peer result body" not in prompt
            # No response was needed to deliver the notification.
            await wire.response()
            [event async for event in adapter.receive_response()]
        finally:
            if inbox is not None:
                await inbox.aclose()
            await adapter.close()
    asyncio.run(exercise())


@pytest.mark.parametrize("terminal_decision", [False, True])
def test_late_notification_cannot_submit_during_sdk_disconnect(tmp_path, terminal_decision):
    from neurath.providers.claude_sdk import ClaudeSession
    from types import SimpleNamespace
    subprocess.run(["git", "init", "-q", tmp_path], check=True)

    async def exercise():
        writes = []
        class Client:
            async def query(self, prompt, **kwargs):
                writes.append(prompt)
            async def disconnect(self):
                await asyncio.sleep(0)
        adapter = ClaudeSession(tmp_path, permission_mode="dontAsk")
        adapter._client, adapter._connected = Client(), True
        adapter._owner = asyncio.current_task()
        adapter.session = Session("claude-code", "claude-agent-sdk", "owned-fixture", str(tmp_path), None, "model", {})
        inbox = execution_claude.ClaudeInbox(adapter)
        # Socket registration has separate coverage; isolate the SDK close race.
        inbox.service = SimpleNamespace(close=lambda: None)
        if terminal_decision:
            assert await inbox.wait_for_obligations() is False
        late = asyncio.create_task(inbox._receive("a" * 64))
        inbox.close()
        await adapter.close()
        result = await late
        assert writes == []
        assert result["delivery"] == "unavailable"
    asyncio.run(exercise())

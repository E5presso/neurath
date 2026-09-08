"""Real SDK control/parser tests over a deterministic wire, without model calls."""

import asyncio
import json

import pytest
from claude_agent_sdk import ClaudeSDKClient, PermissionResultDeny, ResultMessage
from claude_agent_sdk._internal.transport import Transport

from neurath.providers import claude_sdk
from neurath.providers.contracts import CreationRejected


class Wire(Transport):
    def __init__(self, root):
        self.root = str(root)
        self.messages = asyncio.Queue()
        self.writes = []
        self.ready = False
        self.initialized = False
        self.options = None
        self.mode = "dontAsk"
        self.native = "owned-native-session"

    async def connect(self):
        self.ready = True

    async def write(self, data):
        message = json.loads(data)
        self.writes.append(message)
        if message["type"] == "control_request":
            await self.messages.put({"type": "control_response", "response": {
                "subtype": "success", "request_id": message["request_id"], "response": {}}})
        elif message["type"] == "user" and not self.initialized:
            self.initialized = True
            await self.messages.put({"type": "system", "subtype": "init",
                "session_id": self.native, "model": "chosen-model",
                "cwd": self.root, "permissionMode": self.mode})

    async def response(self, *, error=False, denials=None, native=None, stop_reason=None):
        await self.messages.put({"type": "assistant", "session_id": native or self.native,
            "message": {"model": "chosen-model", "content": [{"type": "text", "text": "answer"}]}})
        await self.messages.put({"type": "result", "subtype": "error_during_execution" if error else "success",
            "duration_ms": 1, "duration_api_ms": 1, "num_turns": 1, "is_error": error,
            "session_id": native or self.native, "result": "answer",
            "permission_denials": denials, "stop_reason": stop_reason})

    async def read_messages(self):
        while True:
            message = await self.messages.get()
            if message is None:
                return
            yield message

    async def close(self):
        self.ready = False
        await self.messages.put(None)

    def is_ready(self):
        return self.ready

    async def end_input(self):
        pass


@pytest.fixture
def wire(tmp_path, monkeypatch):
    transport = Wire(tmp_path)

    def factory(*, options):
        transport.options = options
        return ClaudeSDKClient(options=options, transport=transport)

    monkeypatch.setattr(claude_sdk, "ClaudeSDKClient", factory)
    return transport


@pytest.mark.parametrize("mismatch", [False, True])
def test_startup_hook_before_init_is_not_session_authority(wire, mismatch):
    async def exercise():
        adapter = claude_sdk.ClaudeSession(wire.root, permission_mode="dontAsk")
        await adapter.connect()
        try:
            await wire.messages.put({"type": "system", "subtype": "hook_started",
                "hook_event": "SessionStart", "session_id": "different" if mismatch else wire.native})
            await adapter.bootstrap()
            await wire.response()
            if mismatch:
                with pytest.raises(ValueError, match="session"):
                    [m async for m in adapter.receive_response()]
            else:
                stream = adapter.receive_response()
                first = await anext(stream)
                assert first.subtype == "hook_started"
                assert adapter.session is None
                [m async for m in stream]
                assert adapter.session.native_session == wire.native
        finally:
            await adapter.close()
    asyncio.run(exercise())


async def prepare(session, wire):
    await session.connect()
    await session.bootstrap()
    await wire.response()
    return [message async for message in session.receive_response()]


def test_real_sdk_query_returns_without_result_and_preserves_host_configuration(wire):
    async def exercise():
        events = []
        session = claude_sdk.ClaudeSession(wire.root, permission_mode="dontAsk",
            event_callback=lambda state, detail: events.append((state, detail)))
        try:
            connected = await session.connect()
            assert connected["native_session"] is None
            receipt = await session.bootstrap()
            assert receipt["delivery"] == "submitted"
            assert events == []  # A stdin write and init are not observed model work.
            await wire.response()
            messages = [message async for message in session.receive_response()]
            assert isinstance(messages[-1], ResultMessage)
            assert session.observed()["native_session"] == wire.native
            assert [state for state, _ in events] == ["started", "completed"]
            assert events[-1][1]["result_acceptance"] is False
            options = wire.options
            assert options.setting_sources == ["user", "project", "local"]
            assert options.system_prompt == {"type": "preset", "preset": "claude_code"}
            assert options.allowed_tools == []
            assert options.resume is None and options.session_id is None
            assert options.model is None and options.fallback_model is None
            assert options.max_turns is None and options.max_budget_usd is None
            assert options.sandbox is None and options.env == {}
        finally:
            await session.close()
        assert not wire.ready
    asyncio.run(exercise())


def test_no_assignment_before_native_policy_observation(wire):
    async def exercise():
        session = claude_sdk.ClaudeSession(wire.root, permission_mode="dontAsk")
        await session.connect()
        try:
            with pytest.raises(ValueError, match="not been observed"):
                await session.query("must not be sent")
            assert not any(item["type"] == "user" for item in wire.writes)
        finally:
            await session.close()
    asyncio.run(exercise())


@pytest.mark.parametrize("mismatch", ["mode", "cwd", "model"])
def test_native_policy_mismatch_prevents_assignment(wire, mismatch):
    async def exercise():
        session = claude_sdk.ClaudeSession(wire.root, permission_mode="dontAsk",
                                          model="different" if mismatch == "model" else None)
        if mismatch == "mode":
            wire.mode = "bypassPermissions"
        if mismatch == "cwd":
            wire.root += "/different"
        try:
            with pytest.raises(CreationRejected):
                await prepare(session, wire)
            assert session.session is None
            assert len([item for item in wire.writes if item["type"] == "user"]) == 1
        finally:
            await session.close()
    asyncio.run(exercise())


def test_active_input_is_deferred_and_later_query_uses_same_sdk_connection(wire):
    async def exercise():
        events = []
        session = claude_sdk.ClaudeSession(wire.root, permission_mode="dontAsk",
            event_callback=lambda state, detail: events.append((state, detail)))
        try:
            await prepare(session, wire)
            await session.query("First assignment")
            steering = await session.steer("Additional authorized detail")
            assert steering["delivery"] == "needs-input" and steering["steering"] is False
            assert session.pending_responses == 1
            await wire.response()
            [message async for message in session.receive_response()]
            assert session.pending_responses == 0
            await session.query("Additional authorized detail")
            assert session.pending_responses == 1
            result = await session.interrupt()
            assert result["status"] == "interrupt-requested"
            assert events[-1][0] == "completed"
            await wire.response(error=True, stop_reason="interrupted")
            [message async for message in session.receive_response()]
            assert session.pending_responses == 0 and events[-1][0] == "cancelled"
            assert wire.writes[-1]["request"]["subtype"] == "interrupt"
            assert [item["message"]["content"] for item in wire.writes if item["type"] == "user"] == [
                claude_sdk.BOOTSTRAP, "First assignment", "Additional authorized detail"]
        finally:
            await session.close()
    asyncio.run(exercise())


def test_permission_request_is_reported_and_never_auto_approved(wire):
    async def exercise():
        events = []
        session = claude_sdk.ClaudeSession(wire.root, permission_mode="default",
            event_callback=lambda state, detail: events.append((state, detail)))
        result = await session._permission("Write", {"file_path": "private-file"}, None)
        assert isinstance(result, PermissionResultDeny) and result.interrupt is True
        assert events[0][0] == "waiting"
        assert "private-file" not in json.dumps(events)
    asyncio.run(exercise())


def test_permission_denied_result_is_waiting_not_completed(wire):
    async def exercise():
        events = []
        session = claude_sdk.ClaudeSession(wire.root, permission_mode="dontAsk",
            event_callback=lambda state, detail: events.append((state, detail)))
        try:
            await session.connect()
            await session.bootstrap()
            await wire.response(denials=[{"tool_name": "Write"}])
            [message async for message in session.receive_response()]
            assert events[-1][0] == "waiting"
        finally:
            await session.close()
    asyncio.run(exercise())


def test_different_native_session_response_is_rejected(wire):
    async def exercise():
        session = claude_sdk.ClaudeSession(wire.root, permission_mode="dontAsk")
        try:
            await prepare(session, wire)
            await session.query("Task")
            await wire.response(native="another-session")
            with pytest.raises(ValueError, match="different session"):
                [message async for message in session.receive_response()]
        finally:
            await session.close()
    asyncio.run(exercise())


def test_connection_cleanup_rejects_other_task(wire):
    async def exercise():
        session = claude_sdk.ClaudeSession(wire.root, permission_mode="dontAsk")
        await session.connect()
        try:
            task = asyncio.create_task(session.close())
            with pytest.raises(ValueError, match="owning asyncio task"):
                await task
            assert wire.ready
        finally:
            await session.close()
    asyncio.run(exercise())


def test_response_wait_has_no_task_deadline_and_defers_active_input(wire, monkeypatch):
    async def exercise():
        session = claude_sdk.ClaudeSession(wire.root, permission_mode="dontAsk")
        try:
            await prepare(session, wire)
            await session.query("Task")
            deadline_calls = []
            original = asyncio.timeout
            def record_deadline(value):
                deadline_calls.append(value)
                return original(value)
            monkeypatch.setattr(claude_sdk.asyncio, "timeout", record_deadline)
            reader = asyncio.create_task(collect(session))
            await asyncio.sleep(0)
            assert not reader.done() and deadline_calls == []
            held = await session.steer("Follow-up")
            assert held["delivery"] == "needs-input" and deadline_calls == []
            await wire.response()
            await reader
            assert session.pending_responses == 0 and deadline_calls == []
            await session.query("Follow-up")
            assert deadline_calls == [30] and session.pending_responses == 1
            await wire.response()
            await collect(session)
            assert session.pending_responses == 0 and deadline_calls == [30]
        finally:
            await session.close()
    async def collect(session):
        return [message async for message in session.receive_response()]
    asyncio.run(exercise())


def test_lost_stream_is_failed_and_never_completed(wire):
    async def exercise():
        events = []
        session = claude_sdk.ClaudeSession(wire.root, permission_mode="dontAsk",
            event_callback=lambda state, detail: events.append((state, detail)))
        try:
            await session.connect()
            await session.bootstrap()
            await wire.messages.put(None)
            with pytest.raises(RuntimeError, match="without a native result"):
                [message async for message in session.receive_response()]
            assert events[-1][0] == "failed"
            assert not any(state == "completed" for state, _ in events)
        finally:
            await session.close()
    asyncio.run(exercise())


def test_failed_query_write_stays_unconfirmed_without_retry(wire, monkeypatch):
    async def exercise():
        events = []
        session = claude_sdk.ClaudeSession(wire.root, permission_mode="dontAsk",
            event_callback=lambda state, detail: events.append((state, detail)))
        try:
            await prepare(session, wire)
            calls = []

            async def failed_write(prompt):
                calls.append(prompt)
                raise TimeoutError("write deadline")

            monkeypatch.setattr(session._client, "query", failed_write)
            with pytest.raises(TimeoutError):
                await session.query("Task")
            assert calls == ["Task"]
            assert session.pending_responses == 1
            assert events[-1][1]["reason"] == "submission-unconfirmed"
        finally:
            await session.close()
    asyncio.run(exercise())


@pytest.mark.parametrize("value", [0, float("inf"), True, 121])
def test_invalid_rpc_deadline_is_rejected(tmp_path, value):
    with pytest.raises(ValueError, match="rpc_timeout"):
        claude_sdk.ClaudeSession(tmp_path, permission_mode="dontAsk", rpc_timeout=value)


def test_unknown_permission_mode_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="permission mode"):
        claude_sdk.ClaudeSession(tmp_path, permission_mode="invented-mode")


def test_native_implementation_bootstrap_requests_normal_claim_and_mcp_observation(wire):
    async def exercise():
        session = claude_sdk.ClaudeSession(wire.root, permission_mode="dontAsk")
        await session.connect()
        try:
            await session.bootstrap(claim_worktree=True)
            prompt = next(item["message"]["content"] for item in wire.writes if item["type"] == "user")
            assert "worktree_claim MCP task tool" in prompt
            assert "session_inspect MCP task tool" in prompt
            assert "session_status MCP task tool" in prompt
        finally:
            await session.close()
    asyncio.run(exercise())

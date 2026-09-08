"""Claude input accounting under faithful active-query coalescing and result races."""

import asyncio
import subprocess

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, SystemMessage, TextBlock

from neurath.agents.store import AgentIdentity, MessageStore
from neurath.providers import claude_sdk, execution_claude

pytest_plugins = ["tests.test_claude_sdk", "tests.test_agent_hooks"]


def test_worker_does_not_expect_a_result_for_coalesced_mid_response_input(tmp_path, monkeypatch):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    clients = []
    class CoalescingClient:
        def __init__(self, **kwargs):
            self.active = False
            self.responses = asyncio.Queue()
            self.writes = []
            self.coalesced = []
            self.completed = 0
            self.closed = False
            clients.append(self)
        async def connect(self):
            pass
        async def query(self, prompt):
            self.writes.append(prompt)
            if self.active:
                self.coalesced.append(prompt)
                return  # Actual mid-turn input may share the already active Result.
            self.active = True
            await self.responses.put(prompt)
        async def receive_response(self):
            await self.responses.get()
            if not self.completed:
                MessageStore(tmp_path).register(AgentIdentity("claude-code", "serial-child", "claude-code:session:serial-child"))
                yield SystemMessage("init", {"session_id": "serial-child", "model": "test-model",
                    "cwd": str(tmp_path), "permissionMode": "plan"})
            yield AssistantMessage(content=[TextBlock("READY")], model="test-model")
            yield ResultMessage("success", 1, 1, False, 1, "serial-child", result="CHILD_REPORT_OK")
            self.completed += 1
            self.active = False
        async def get_mcp_status(self):
            assert not self.active
            return {"mcpServers": []}
        async def interrupt(self):
            pass
        async def disconnect(self):
            self.closed = True
    monkeypatch.setattr(claude_sdk, "ClaudeSDKClient", CoalescingClient)
    async def inventory(*args, **kwargs):
        return None
    monkeypatch.setattr("neurath.providers.model_inventory.claude_inventory", inventory)
    report = {"waiting": None, "stages": {name: {"status": "verified"}
        for name in ("installation", "activation", "policy")}}
    monkeypatch.setattr(execution_claude, "_readiness", lambda _: report)
    # This test isolates response accounting; native quiescence has separate tests.
    monkeypatch.setattr(execution_claude, "_quiescent_readiness", lambda *a: report, raising=False)
    async def exercise():
        result = {"implementation_dispatched": False, "status": "failed", "text": ""}
        async with asyncio.timeout(0.75):
            return await execution_claude._run(tmp_path, "Read and report", None, "plan", None, result)
    result = asyncio.run(exercise())
    assert result["status"] == "completed"
    assert result["text"] == "CHILD_REPORT_OK"
    assert clients[0].coalesced == []
    assert clients[0].completed == 2 and len(clients[0].writes) == 2
    assert clients[0].closed


def test_dispatch_cannot_write_inside_preparation_result_stream(wire):
    async def exercise():
        adapter = claude_sdk.ClaudeSession(wire.root, permission_mode="dontAsk")
        try:
            await adapter.connect()
            await adapter.bootstrap()
            stream = adapter.receive_response()
            await anext(stream)  # Native init, with preparation still active.
            with pytest.raises(ValueError, match="completed.*drained|active"):
                await adapter.dispatch("Assignment must be a separate native query")
            assert adapter.pending_responses == 1
            await wire.response()
            [item async for item in stream]
            await adapter.dispatch("Assignment after preparation result")
            assert adapter.pending_responses == 1
            await wire.response()
            [item async for item in adapter.receive_response()]
            assert adapter.pending_responses == 0
        finally:
            await adapter.close()
    asyncio.run(exercise())


def test_result_before_query_write_returns_does_not_allow_overlapping_query(wire, monkeypatch):
    from tests.test_claude_sdk import prepare
    async def exercise():
        adapter = claude_sdk.ClaudeSession(wire.root, permission_mode="dontAsk")
        release, written = asyncio.Event(), asyncio.Event()
        try:
            await prepare(adapter, wire)
            original = adapter._client.query
            async def delayed(prompt):
                await original(prompt)
                written.set()
                await release.wait()
            monkeypatch.setattr(adapter._client, "query", delayed)
            submission = asyncio.create_task(adapter.query("First"))
            await written.wait()
            await wire.response()
            [item async for item in adapter.receive_response()]
            assert adapter.pending_responses == 0 and not submission.done()
            with pytest.raises(ValueError, match="active|write"):
                await adapter.query("Cannot race the unsettled write")
            release.set()
            await submission
            monkeypatch.setattr(adapter._client, "query", original)
            await adapter.query("Second serial query")
            assert adapter.pending_responses == 1
            await wire.response()
            [item async for item in adapter.receive_response()]
            assert adapter.pending_responses == 0
        finally:
            release.set()
            await adapter.close()
    asyncio.run(exercise())


def test_quiescent_readiness_revalidates_closed_native_turn(sessions, monkeypatch):
    from types import SimpleNamespace
    from neurath.providers import readiness
    from neurath.providers.contracts import Session
    root, invoke = sessions
    monkeypatch.setattr(readiness, "_installation", lambda _: readiness._stage("verified", evidence={"distribution": "fixture"}))
    code, output, diagnostic = invoke("claude-code", "ui", "PreToolUse", permission_mode="plan",
        tool_name="mcp__neurath_collaboration__session_status", tool_use_id="prep-policy", tool_input={})
    assert code == 0, diagnostic
    session = Session("claude-code", "claude-agent-sdk", "ui", str(root), None, "model", {"requested": {"permission_mode": "plan"}})
    prepared = execution_claude._readiness(session)
    assert execution_claude._ready(prepared, "plan"), prepared
    code, output, diagnostic = invoke("claude-code", "ui", "Stop")
    assert code == 0, (output, diagnostic)
    adapter = SimpleNamespace(session=session, permission_mode="plan", response_active=False, _connected=True)
    report = execution_claude._quiescent_readiness(adapter, prepared)
    assert execution_claude._ready(report, "plan"), report
    assert report["scope"] == "owned-quiescent-session"
    assert report["stages"]["activation"]["evidence"]["foreground_status"] == "closed"
    assert invoke("claude-code", "ui", "UserPromptSubmit", prompt="Changed user scope")[0] == 0
    assert invoke("claude-code", "ui", "PreToolUse", permission_mode="plan",
        tool_name="mcp__neurath_collaboration__session_status", tool_use_id="new-user-policy", tool_input={})[0] == 0
    assert execution_claude._ready(execution_claude._readiness(session), "plan")
    changed = execution_claude._quiescent_readiness(adapter, prepared)
    assert not execution_claude._ready(changed, "plan")


def test_inbox_holds_active_notifications_until_result_then_replays_once(wire):
    from tests.test_claude_sdk import prepare
    from neurath.agents.delivery import receipt
    from neurath.providers.execution_claude import ClaudeInbox
    subprocess.run(["git", "init", "-q", wire.root], check=True)
    async def exercise():
        adapter = claude_sdk.ClaudeSession(wire.root, permission_mode="dontAsk")
        inbox = None
        try:
            await prepare(adapter, wire)
            store = MessageStore(wire.root)
            own = AgentIdentity("claude-code", wire.native, "own")
            peer = AgentIdentity("codex", "peer", "peer")
            store.register(own)
            store.register(peer)
            await adapter.query("Active assignment")
            inbox = ClaudeInbox(adapter).start()
            sent = store.send(peer.address, own.address, "A concurrent report", key="during-response")
            def held():
                with inbox.service.changed:
                    assert inbox.service.changed.wait_for(lambda: (receipt(store, sent["id"]) or {}).get("status") == "needs-input", timeout=2)
            await asyncio.to_thread(held)
            assert adapter.pending_responses == 1
            assert len([item for item in wire.writes if item["type"] == "user"]) == 2
            await wire.response()
            [item async for item in adapter.receive_response()]
            assert adapter.pending_responses == 0
            inbox.response_completed()
            async with asyncio.timeout(2):
                assert await inbox.wait_for_obligations()
            assert adapter.pending_responses == 1
            assert len([item for item in wire.writes if item["type"] == "user"]) == 3
            await wire.response()
            [item async for item in adapter.receive_response()]
            store.message(own.address, sent["id"])
            store.acknowledge(own.address, sent["id"])
            assert not await inbox.wait_for_obligations()
            assert adapter.pending_responses == 0
        finally:
            if inbox:
                await inbox.aclose()
            await adapter.close()
    asyncio.run(exercise())


@pytest.mark.parametrize("change", ["claim", "installation", "policy"])
def test_quiescent_write_readiness_rejects_changed_preparation(sessions, monkeypatch, change):
    from types import SimpleNamespace
    from neurath.providers import readiness
    from neurath.providers.contracts import Session
    from scripts.agent_harness.session_kernel import SessionId, SessionKernel, SessionLocator
    from scripts.agent_harness.worktree_registry import WorktreeClaim, WorktreeIdentityResolver, WorktreeRegistry
    root, invoke = sessions
    monkeypatch.setattr(readiness, "_installation", lambda _: readiness._stage("verified", evidence={"distribution": "fixture"}))
    state = SessionKernel(SessionLocator.from_worktree(root)).inspect(SessionId("ui"))
    canonical = WorktreeIdentityResolver().resolve(root)
    registry = WorktreeRegistry(SessionLocator.from_worktree(root))
    claim = registry.claim(WorktreeClaim(worktree_id=canonical.worktree_id, path=root,
        session_id=state.session.id, actor_id=state.session.root_actor_id))
    assert invoke("claude-code", "ui", "PreToolUse", permission_mode="bypassPermissions",
        tool_name="mcp__neurath_collaboration__session_status", tool_use_id="write-policy", tool_input={})[0] == 0
    session = Session("claude-code", "claude-agent-sdk", "ui", str(root), None, "model", {"requested": {"permission_mode": "bypassPermissions"}})
    prepared = execution_claude._readiness(session)
    assert execution_claude._ready(prepared, "bypassPermissions"), prepared
    assert invoke("claude-code", "ui", "Stop")[0] == 0
    adapter = SimpleNamespace(session=session, permission_mode="bypassPermissions", response_active=False, _connected=True)
    assert execution_claude._ready(execution_claude._quiescent_readiness(adapter, prepared), "bypassPermissions")
    if change == "claim":
        registry.release(claim)
    elif change == "installation":
        monkeypatch.setattr(readiness, "_installation", lambda _: readiness._stage("verified", evidence={"distribution": "changed"}))
    else:
        session.policy["requested"]["permission_mode"] = "dontAsk"
    assert not execution_claude._ready(execution_claude._quiescent_readiness(adapter, prepared), "bypassPermissions")

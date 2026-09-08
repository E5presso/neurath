"""A failed receiver wakes its owning provider, without polling or fake native events."""

import asyncio
import queue
import threading

import pytest

from neurath.agents import delivery
from neurath.providers.execution_claude import ClaudeInbox
from tests.test_agent_delivery import message

pytest_plugins = ["tests.test_agent_delivery", "tests.test_provider_transport", "tests.test_claude_sdk"]


def test_fatal_receiver_failure_reports_once_after_endpoint_cleanup(store, monkeypatch):
    notified = threading.Event()
    errors = []
    def failed(error):
        errors.append(error)
        with store.connection() as db:
            assert db.execute("SELECT 1 FROM delivery_endpoints WHERE address='codex:issuer'").fetchone() is None
        notified.set()
    class BrokenEvents:
        def __init__(self, *args):
            pass
        def wait(self, timeout=None):
            raise OSError("private raw detail must not be sent")
        def close(self):
            pass
    monkeypatch.setattr(delivery, "StoreEvents", BrokenEvents)
    with delivery.DeliveryService(store, "codex:issuer", lambda _: {}, on_failure=failed):
        assert notified.wait(2)
    assert len(errors) == 1
    assert errors[0].error_type == "OSError"
    assert "private" not in str(errors[0])
    identifier = message(store)
    assert store.message("codex:issuer", identifier)["status"] == "queued"


def test_owned_dependency_failure_wakes_codex_unbounded_event_wait(server):
    body = """for line in sys.stdin:
    request=json.loads(line)
    if request.get('method') == 'initialize':
        print(json.dumps({'id':request['id'],'result':{}}),flush=True)
"""
    with server(body) as host:
        entered = threading.Event()
        original = host._next
        def waiting(*a, **k):
            entered.set()
            return original(*a, **k)
        host._next = waiting
        observed = queue.Queue()
        def consume():
            try:
                host.event(lambda _: True, timeout=None)
            except RuntimeError as error:
                observed.put(error)
        thread = threading.Thread(target=consume)
        thread.start()
        assert entered.wait(1)
        host.fail_owned_dependency(delivery.DeliveryServiceError("OSError"))
        failure = observed.get(timeout=2)
        thread.join(2)
        assert not thread.is_alive()
        assert isinstance(failure, delivery.DeliveryServiceError)


@pytest.mark.parametrize("before_wait", [False, True])
def test_claude_service_failure_wakes_supervision_and_emits_error(wire, before_wait):
    from neurath.agents.lifecycle import TaskLifecycle
    from neurath.agents.store import AgentIdentity, MessageStore
    from neurath.providers.claude_sdk import ClaudeSession
    import subprocess
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
            [item async for item in adapter.receive_response()]
            store = MessageStore(wire.root)
            own = AgentIdentity("claude-code", wire.native, "fixture-own")
            peer = AgentIdentity("codex", "fixture-peer", "fixture-peer")
            store.register(own)
            store.register(peer)
            TaskLifecycle(store).bind(own.address, peer.address, key="pending", transport="peer-assignment")
            inbox = ClaudeInbox(adapter).start()
            if before_wait:
                inbox.service.terminal_error = delivery.DeliveryServiceError("OSError")
                waiter = asyncio.create_task(inbox.wait_for_obligations())
            else:
                waiter = asyncio.create_task(inbox.wait_for_obligations())
                await asyncio.sleep(0)
                assert not waiter.done()
                inbox._service_failed(delivery.DeliveryServiceError("OSError"))
            with pytest.raises(delivery.DeliveryServiceError, match="OSError"):
                async with asyncio.timeout(2):
                    await waiter
            assert any(state == "error" and detail.get("reason") == "delivery-service-failed" for state, detail in events)
            assert adapter.pending_responses == 0
        finally:
            if inbox:
                await inbox.aclose()
            await adapter.close()
    asyncio.run(exercise())


def test_codex_worker_emits_error_and_cannot_claim_completion(monkeypatch):
    from types import SimpleNamespace
    from neurath.providers import execution
    from tests.test_provider_execution import _terminal_fixture
    inbox = SimpleNamespace(close=lambda: None)
    calls = _terminal_fixture(monkeypatch, inbox)
    host_type = execution.CodexStdio
    original = host_type.event
    seen = []
    def failed_wait(self, *a, **k):
        if seen:
            raise delivery.DeliveryServiceError("OSError")
        seen.append(True)
        return original(self, *a, **k)
    monkeypatch.setattr(host_type, "event", failed_wait)
    reports = []
    result = execution.run("/parent", worktree="/work", assignment="Work", mode="workspace-write",
        approval_policy="never", collaboration_mode="default", event_callback=lambda *event: reports.append(event))
    assert result["status"] == "failed"
    assert result["delivery_failure"]["reason"] == "delivery-service-failed"
    assert ("error", {"reason": "delivery-service-failed", "error_type": "OSError", "native_session": "native"}) in reports
    assert calls[-2:] == ["cancel", "host-close"]


def test_queued_native_completion_cannot_outrun_receiver_failure():
    from tests.test_provider_supervision import _isolated_inbox
    inbox = _isolated_inbox(lambda _: {})
    inbox.service.terminal_error = delivery.DeliveryServiceError("OSError")
    with pytest.raises(delivery.DeliveryServiceError):
        inbox.complete_turn("original", "original", successful=True)


def test_unavailable_after_consumed_native_resume_retries_without_another_event(store):
    from tests.test_agent_delivery import accepted, wait
    done = threading.Event()
    calls = []
    def deliver(identifier):
        calls.append(identifier)
        if len(calls) == 1:
            return {"delivery": "needs-input"}
        if len(calls) == 2:
            return {"delivery": "unavailable"}
        store.message("codex:issuer", identifier)
        store.acknowledge("codex:issuer", identifier)
        done.set()
        return accepted(identifier)
    identifier = message(store)
    with delivery.DeliveryService(store, "codex:issuer", deliver, retry_delay=0.02) as service:
        wait(service, store, identifier, "needs-input")
        service.resume()
        assert done.wait(2), "unavailable was held after the only native completion event"
    assert calls == [identifier] * 3

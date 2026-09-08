"""Event-driven replay must survive a lost notification after durable commit."""

import os
import sqlite3
import subprocess
import sys
import threading

import pytest

from neurath.agents import delivery
from neurath.agents.delivery import DeliveryService, delivery_status
from tests.test_agent_delivery import accepted, message

pytest_plugins = ["tests.test_agent_delivery"]


def test_conversation_body_read_allows_recipient_ack(store):
    identifier = message(store)
    conv = store.message("codex:worker", identifier)["conversation"]
    body = store.conversation("codex:issuer", conv)
    assert body["messages"][0]["body"] == "task result"
    assert store.acknowledge("codex:issuer", identifier)["status"] == "received"


def test_committed_message_survives_total_post_commit_notification_loss(store, monkeypatch):
    ready, received = threading.Event(), threading.Event()
    class ReadyService(DeliveryService):
        def _pending(self, **kwargs):
            result = super()._pending(**kwargs)
            ready.set()
            return result
    def deliver(identifier):
        store.message("codex:issuer", identifier)
        store.acknowledge("codex:issuer", identifier)
        received.set()
        return accepted(identifier)
    with ReadyService(store, "codex:issuer", deliver, retry_delay=300) as service:
        assert ready.wait(2)
        monkeypatch.setattr(delivery, "dispatch", lambda *a: {"delivery": "queued"})
        identifier = message(store)
        assert received.wait(2), "durable commit remained stranded without any datagram"
        assert store.message("codex:issuer", identifier)["status"] == "received"
        assert not service.failure


def test_late_repair_result_cannot_quarantine_after_endpoint_close(store):
    started, release = threading.Event(), threading.Event()
    def deliver(_identifier):
        started.set()
        assert release.wait(5)
        return {"delivery": "repair-required", "reason": "recipient-binding"}
    identifier = message(store)
    service = DeliveryService(store, "codex:issuer", deliver).__enter__()
    try:
        assert started.wait(2)
        service.close()
    finally:
        release.set()
        service._thread.join(timeout=2)
    assert delivery_status(store, "codex:issuer", identifier)["hold"] is None


def test_late_repair_result_cannot_change_successor_generation(store):
    started, release = threading.Event(), threading.Event()
    def deliver(_identifier):
        started.set()
        assert release.wait(5)
        return {"delivery": "repair-required", "reason": "recipient-binding"}
    identifier = message(store)
    service = DeliveryService(store, "codex:issuer", deliver).__enter__()
    try:
        assert started.wait(2)
        with store.connection() as db:
            db.execute("UPDATE delivery_endpoints SET generation='replacement' WHERE address=?", (service.address,))
        release.set()
        with service.changed:
            assert service.changed.wait_for(lambda: delivery_status(store, "codex:issuer", identifier)["recent_attempts"][0]["status"] != "sending", timeout=2)
        assert delivery_status(store, "codex:issuer", identifier)["hold"] is None
    finally:
        release.set()
        service.close()


@pytest.mark.parametrize("journal_mode", ["DELETE", "WAL"])
def test_publisher_exit_after_commit_reaches_live_receiver(store, journal_mode):
    connection = sqlite3.connect(store.path)
    assert connection.execute("PRAGMA journal_mode=" + journal_mode).fetchone()[0].upper() == journal_mode
    ready, received = threading.Event(), threading.Event()
    class ReadyService(DeliveryService):
        def _pending(self, **kwargs):
            result = super()._pending(**kwargs)
            ready.set()
            return result
    delivered = []
    def deliver(identifier):
        delivered.append(identifier)
        store.message("codex:issuer", identifier)
        store.acknowledge("codex:issuer", identifier)
        received.set()
        return accepted(identifier)
    code = """import os,sys
from neurath.agents.store import MessageStore
from neurath.agents import delivery
delivery.dispatch = lambda *args: os._exit(0)
MessageStore(sys.argv[1]).send('codex:worker','codex:issuer','committed-before-exit',key='exit-after-commit')
raise RuntimeError('post-commit exit was not reached')
"""
    try:
        with ReadyService(store, "codex:issuer", deliver, retry_delay=300):
            assert ready.wait(2)
            subprocess.run([sys.executable, "-c", code, str(store.worktree)], env=dict(os.environ), check=True, timeout=5)
            assert received.wait(2), "publisher exited after commit and the live receiver missed the message"
            assert len(delivered) == 1
            assert store.message("codex:issuer", delivered[0])["body"] == "committed-before-exit"
    finally:
        connection.close()


def test_wal_receiver_does_not_generate_an_idle_event_feedback_loop(store):
    connection = sqlite3.connect(store.path)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.close()
    ready, repeated = threading.Event(), threading.Event()
    class CountService(DeliveryService):
        count = 0
        def _pending(self, **kwargs):
            self.count += 1
            result = super()._pending(**kwargs)
            ready.set()
            if self.count > 3:
                repeated.set()
            return result
    with CountService(store, "codex:issuer", accepted):
        assert ready.wait(2)
        assert not repeated.wait(0.15), "receiver reads generated their own endless WAL file events"

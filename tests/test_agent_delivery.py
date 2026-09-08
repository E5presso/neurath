"""Real UNIX socket push delivery, including races and durable uncertainty."""

import os
from pathlib import Path
import socket
import subprocess
import threading

import pytest

from neurath.agents.delivery import DeliveryService, dispatch, receipt
from neurath.agents.store import AgentIdentity, MessageStore


@pytest.fixture
def store(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    value = MessageStore(tmp_path)
    for name in ("issuer", "worker", "other"):
        value.register(AgentIdentity("codex", name, "actor:" + name))
    return value


def message(store, key="one", recipient="codex:issuer"):
    return store.send("codex:worker", recipient, "task result", key=key)["id"]


def wait(service, store, message_id, status):
    with service.changed:
        assert service.changed.wait_for(
            lambda: (receipt(store, message_id) or {}).get("status") == status, timeout=3)


def accepted(message_id):
    return {"delivery": "submitted", "transport": "fixture-native", "native_turn": message_id[:8]}


def test_socket_event_pushes_exact_id_and_marks_only_actual_submission(store):
    calls = []
    def deliver(message_id):
        calls.append(message_id)
        return accepted(message_id)
    with DeliveryService(store, "codex:issuer", deliver) as service:
        assert os.stat(Path(service.endpoint).parent).st_mode & 0o777 == 0o700
        assert os.stat(service.endpoint).st_mode & 0o777 == 0o600
        identifier = message(store)
        assert dispatch(store, identifier)["delivery"] in {"notified", "sending", "submitted"}
        wait(service, store, identifier, "submitted")
        assert store.message("codex:issuer", identifier)["status"] == "submitted"
        assert dispatch(store, identifier)["delivery"] == "notified"
        assert calls == [identifier]
    assert not Path(service.endpoint).exists()


def test_registration_delivers_messages_committed_before_receiver_started(store):
    identifier = message(store)
    assert dispatch(store, identifier)["delivery"] == "queued"
    with DeliveryService(store, "codex:issuer", accepted) as service:
        wait(service, store, identifier, "submitted")


def test_uncertain_result_survives_service_restart_and_is_redelivered(store):
    calls = []
    def lost_response(identifier):
        calls.append(identifier)
        raise TimeoutError("private provider diagnostic must not be persisted")
    identifier = message(store)
    with DeliveryService(store, "codex:issuer", lost_response) as service:
        wait(service, store, identifier, "uncertain")
        assert dispatch(store, identifier)["delivery"] == "notified"
        assert receipt(store, identifier)["result"] == {"error_type": "TimeoutError"}
    with DeliveryService(store, "codex:issuer", accepted) as service:
        wait(service, store, identifier, "submitted")
        assert calls == [identifier]
        assert store.message("codex:issuer", identifier)["status"] == "submitted"
        with store.connection() as db:
            assert [row[0] for row in db.execute("SELECT status FROM delivery_history WHERE message=? ORDER BY id", (identifier,))] == ["uncertain", "submitted"]


def test_waiting_requires_explicit_native_resume_event(store):
    calls = []
    def deliver(identifier):
        calls.append(identifier)
        return {"delivery": "needs-input"} if len(calls) == 1 else accepted(identifier)
    identifier = message(store)
    with DeliveryService(store, "codex:issuer", deliver) as service:
        wait(service, store, identifier, "needs-input")
        assert dispatch(store, identifier)["delivery"] == "needs-input"
        assert calls == [identifier]
        service.resume()
        wait(service, store, identifier, "submitted")
        assert calls == [identifier, identifier]


def test_receiver_rejects_other_recipient_and_malformed_datagrams(store):
    calls = []
    with DeliveryService(store, "codex:issuer", lambda identifier: calls.append(identifier) or accepted(identifier)) as service:
        other = message(store, recipient="codex:other")
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sender:
            sender.sendto(other.encode(), service.endpoint)
            sender.sendto(b"x" * 64, service.endpoint)
            sender.sendto(b"x" * 200, service.endpoint)
        own = message(store, "own")
        dispatch(store, own)
        wait(service, store, own, "submitted")
        assert calls == [own]
        assert receipt(store, other) is None


def test_duplicate_live_owner_cannot_replace_endpoint(store):
    with DeliveryService(store, "codex:issuer", accepted) as service:
        with pytest.raises(BlockingIOError):
            with DeliveryService(store, "codex:issuer", accepted):
                pass
        identifier = message(store)
        dispatch(store, identifier)
        wait(service, store, identifier, "submitted")


def test_close_does_not_wait_indefinitely_for_blocked_provider(store):
    started, release = threading.Event(), threading.Event()
    def deliver(identifier):
        started.set()
        assert release.wait(5)
        return accepted(identifier)
    identifier = message(store)
    service = DeliveryService(store, "codex:issuer", deliver).__enter__()
    try:
        assert started.wait(3)
        service.close()
        assert service._thread.is_alive()
        assert receipt(store, identifier)["status"] == "sending"
        another = message(store, "after-close")
        assert dispatch(store, another)["delivery"] == "queued"
    finally:
        release.set()
        service._thread.join(timeout=3)
    assert not service._thread.is_alive()
    assert not Path(service.endpoint).exists()


def test_old_receiver_rejects_replaced_generation_without_invoking_provider(store):
    calls = []
    with DeliveryService(store, "codex:issuer", lambda identifier: calls.append(identifier) or accepted(identifier)) as service:
        with store.connection() as db:
            db.execute("UPDATE delivery_endpoints SET generation='replacement' WHERE address='codex:issuer'")
        identifier = message(store)
        service._deliver(identifier)
        assert calls == []
        assert receipt(store, identifier) is None
    with store.connection() as db:
        assert db.execute("SELECT generation FROM delivery_endpoints WHERE address='codex:issuer'").fetchone()[0] == "replacement"


@pytest.mark.parametrize("status", ["failed", "uncertain"])
def test_native_resume_respects_message_backoff(store, status):
    calls = []
    def deliver(identifier):
        calls.append(identifier)
        return {"delivery": status}
    identifier = message(store)
    with DeliveryService(store, "codex:issuer", deliver) as service:
        wait(service, store, identifier, status)
        service.resume()
        followup = message(store, "followup")
        dispatch(store, followup)
        wait(service, store, followup, status)
        assert calls == [identifier, followup]

"""No-omission delivery contract, independent of provider model quality."""

import threading

import pytest

from neurath.agents.delivery import DeliveryService, receipt
from tests.test_agent_delivery import accepted, message, store, wait


@pytest.mark.parametrize("state", ["sending", "failed", "uncertain", "submitted"])
def test_new_owned_connection_replays_every_unacknowledged_state(store, state):
    identifier = message(store)
    from neurath.agents.delivery import _schema
    _schema(store)
    with store.connection() as db:
        db.execute("INSERT INTO delivery_attempts VALUES(?,?,?,?,?,?)",
                   (identifier, "codex:issuer", "dead-generation", state, "{}", 0))
    if state == "submitted":
        store.submitted("codex:worker", identifier, transport="old-native")
    delivered = []
    with DeliveryService(store, "codex:issuer", lambda key: delivered.append(key) or accepted(key)) as service:
        with service.changed:
            assert service.changed.wait_for(lambda: delivered == [identifier], timeout=2)
        wait(service, store, identifier, "submitted")
    assert store.message("codex:issuer", identifier)["body"] == "task result"


def test_ack_deadline_retries_same_message_without_status_polling(store):
    done = threading.Event()
    calls = []
    def deliver(identifier):
        calls.append(identifier)
        if len(calls) == 2:
            store.message("codex:issuer", identifier)
            store.acknowledge("codex:issuer", identifier)
            done.set()
        return accepted(identifier)
    identifier = message(store)
    with DeliveryService(store, "codex:issuer", deliver, retry_delay=0.02) as service:
        assert done.wait(2)
        wait(service, store, identifier, "submitted")
    assert calls == [identifier, identifier]
    assert store.message("codex:issuer", identifier)["status"] == "received"


def test_ack_requires_body_and_failed_lookup_keeps_message_pending(store):
    identifier = message(store)
    with pytest.raises(ValueError, match="body"):
        store.acknowledge("codex:issuer", identifier)
    with pytest.raises(ValueError, match="unknown message"):
        store.message("codex:issuer", "missing")
    with pytest.raises(ValueError, match="body"):
        store.acknowledge("codex:issuer", identifier)
    store.message("codex:issuer", identifier)
    assert store.acknowledge("codex:issuer", identifier)["status"] == "received"
    assert store.acknowledge("codex:issuer", identifier)["status"] == "received"


def test_expiry_and_close_do_not_discard_unread_message(store):
    identifier = message(store)
    conversation = store.message("codex:worker", identifier)["conversation"]
    with store.connection() as db:
        db.execute("UPDATE conversations SET expires=0 WHERE id=?", (conversation,))
    assert store.close("codex:worker", conversation)["status"] == "pending"
    assert [item["id"] for item in store.inbox("codex:issuer")] == [identifier]
    store.acknowledge("codex:issuer", identifier)
    assert store.close("codex:worker", conversation)["status"] == "closed"


def test_repair_required_retains_body_and_redrive_is_owned_and_revisioned(store):
    from neurath.agents.delivery import quarantine, redrive, delivery_status
    identifier = message(store)
    held = quarantine(store, identifier, reason="envelope-version")
    with pytest.raises(ValueError, match="participant"):
        redrive(store, "codex:other", identifier, expected_revision=held["revision"], repair_reference="migration-2", key="repair")
    with pytest.raises(ValueError, match="revision"):
        redrive(store, "codex:worker", identifier, expected_revision=999, repair_reference="migration-2", key="repair")
    assert delivery_status(store, "codex:issuer", identifier)["hold"]["reason"] == "envelope-version"
    called = threading.Event()
    with DeliveryService(store, "codex:issuer", lambda key: called.set() or accepted(key)) as service:
        assert not called.wait(0.05)
        released = redrive(store, "codex:worker", identifier, expected_revision=held["revision"], repair_reference="migration-2", key="repair")
        assert released["message_id"] == identifier
        assert called.wait(2)
        wait(service, store, identifier, "submitted")
    assert store.message("codex:issuer", identifier)["body"] == "task result"
    assert redrive(store, "codex:worker", identifier, expected_revision=held["revision"], repair_reference="migration-2", key="repair") == released


def test_hook_preview_is_not_full_body_receipt(store):
    identifier = message(store)
    assert identifier in store.context("codex:issuer")
    with pytest.raises(ValueError, match="body"):
        store.acknowledge("codex:issuer", identifier)

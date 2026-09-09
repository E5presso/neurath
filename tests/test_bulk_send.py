"""Bulk admission is one durable transaction with independent recipient delivery."""
import sqlite3

import pytest

from neurath.agents import delivery
from neurath.runtime.task_schema import arguments

pytest_plugins = ["tests.test_messaging"]


def test_bulk_retry_preserves_message_ids_after_reordering(peers):
    store, sender, a, b = peers
    first = store.send_many(sender, [
        {"key": "shared", "message": "Review", "to": [a, b]},
        {"key": "extra", "message": "Verify", "to": [b], "kind": "update"},
    ])
    replay = store.send_many(sender, [
        {"key": "extra", "message": "Verify", "to": [b], "kind": "update"},
        {"key": "shared", "message": "Review", "to": [b, a]},
    ])
    assert {row["id"] for row in first} == {row["id"] for row in replay}
    assert len(store.inbox(a)) == 1
    assert len(store.inbox(b)) == 2


def test_bulk_late_conflict_rolls_back_every_new_message(peers, monkeypatch):
    store, sender, a, b = peers
    store.send_many(sender, [{"key": "fixed", "message": "Original", "to": [a]}])
    notifications = []
    monkeypatch.setattr(delivery, "dispatch", lambda _store, message: notifications.append(message))
    with pytest.raises(ValueError, match="reused"):
        store.send_many(sender, [
            {"key": "new", "message": "Must roll back", "to": [b]},
            {"key": "fixed", "message": "Changed", "to": [a]},
        ])
    assert store.inbox(b) == []
    assert notifications == []


def test_bulk_notifications_observe_the_whole_committed_batch(peers, monkeypatch):
    store, sender, a, b = peers
    notifications = []

    def notified(current, message):
        with sqlite3.connect(current.path) as db:
            count = db.execute("SELECT count(*) FROM messages WHERE body='Shared'").fetchone()[0]
        assert count == 2
        notifications.append(message)

    monkeypatch.setattr(delivery, "dispatch", notified)
    rows = store.send_many(sender, [{"key": "atomic", "message": "Shared", "to": [a, b]}])
    assert notifications == [row["id"] for row in rows]


def test_bulk_schema_preserves_single_send_and_rejects_ambiguous_or_oversized_input():
    legacy = {"key": "one", "message": "Single", "to": "codex:one"}
    bulk = {"messages": [{"key": "many", "message": "Shared", "to": ["codex:one", "codex:two"]}]}
    assert arguments("collaboration_send", legacy)["to"] == "codex:one"
    assert arguments("collaboration_send", bulk)["messages"] == bulk["messages"]
    for invalid in (
        {}, {"messages": []}, {**legacy, **bulk}, {**bulk, "kind": "question"},
        {"messages": [{"key": "a", "message": "x", "to": ["a", "a"]}]},
        {"messages": [{"key": "a", "message": "한" * 10923, "to": ["a"]}]},
        {"messages": [{"key": str(i), "message": "x", "to": [str(j) for j in range(32)]} for i in range(4)]},
        {"messages": [{"key": "a", "message": "x" * 16000, "to": [str(i) for i in range(17)]}]},
    ):
        with pytest.raises(ValueError):
            arguments("collaboration_send", invalid)

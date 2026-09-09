"""Common runtime transactions preserve revisions and reject competing writers."""
from concurrent.futures import ThreadPoolExecutor

import pytest


def database(root):
    from neurath._assets.scripts.agent_harness.runtime_database import RuntimeDatabase

    return RuntimeDatabase(root)


def test_runtime_transaction_rolls_back_related_records(tmp_path):
    store = database(tmp_path)
    with pytest.raises(RuntimeError, match="interrupted"):
        with store.transaction() as tx:
            tx.put("session", "one", b"state", expected_revision=None)
            tx.put("tasks", "one", b"task list", expected_revision=None)
            raise RuntimeError("interrupted")
    with database(tmp_path).transaction() as tx:
        assert tx.get("session", "one") is None
        assert tx.get("tasks", "one") is None


def test_runtime_concurrent_compare_and_swap_has_one_winner(tmp_path):
    from neurath._assets.scripts.agent_harness.runtime_database import RecordConflict

    store = database(tmp_path)
    with store.transaction() as tx:
        assert tx.put("session", "one", b"initial", expected_revision=None).revision == 0

    def replace(index):
        try:
            with database(tmp_path).transaction() as tx:
                tx.put("session", "one", str(index).encode(), expected_revision=0)
            return "committed"
        except RecordConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=4) as workers:
        results = list(workers.map(replace, range(4)))
    assert results.count("committed") == 1
    assert results.count("conflict") == 3
    with store.transaction() as tx:
        assert tx.get("session", "one").revision == 1


def test_runtime_migration_validates_before_commit_and_detects_legacy_drift(tmp_path):
    import json

    from neurath._assets.scripts.agent_harness.runtime_database import LegacyStateChanged

    store = database(tmp_path)
    legacy = tmp_path / "old.json"
    legacy.write_text('{"revision":7,"identity":"one"}')

    def validate(data):
        value = json.loads(data)
        if value["identity"] != "one":
            raise ValueError("identity mismatch")
        return value["revision"]

    first = store.import_legacy("session", "one", legacy, validate)
    assert first.revision == 7
    assert store.import_legacy("session", "one", legacy, validate) == first
    legacy.write_text('{"revision":8,"identity":"one"}')
    with pytest.raises(LegacyStateChanged):
        with store.transaction() as tx:
            tx.get("session", "one")
    bad = tmp_path / "bad.json"
    bad.write_text('{"revision":0,"identity":"other"}')
    with pytest.raises(ValueError, match="identity mismatch"):
        store.import_legacy("session", "other", bad, validate)
    with store.transaction() as tx:
        assert tx.get("session", "other") is None


def test_runtime_database_rejects_symlink_journals_and_corrupt_records(tmp_path):
    from neurath._assets.scripts.agent_harness.runtime_database import CorruptRecord

    store = database(tmp_path)
    with store.transaction() as tx:
        tx.put("session", "one", b"valid", expected_revision=None)
    import sqlite3

    with sqlite3.connect(store.path) as db:
        db.execute("UPDATE runtime_records SET payload=?", (b"tampered",))
    with pytest.raises(CorruptRecord):
        with store.transaction() as tx:
            tx.get("session", "one")
    journal = store.path.with_name(store.path.name + "-journal")
    journal.symlink_to(tmp_path / "outside")
    with pytest.raises(ValueError, match="symlink"):
        with store.transaction():
            pytest.fail("unsafe database opened")


def test_nested_runtime_transactions_share_commit_and_notification_boundary(tmp_path):
    store = database(tmp_path)
    delivered = []
    with store.connection() as outer:
        outer.after_commit["notice"] = lambda: delivered.append("committed")
        with database(tmp_path).transaction() as tx:
            assert tx.connection is outer
            tx.put("session", "one", b"state", expected_revision=None)
        assert delivered == []
    assert delivered == ["committed"]
    with store.transaction() as tx:
        assert tx.get("session", "one").payload == b"state"


def test_nested_runtime_failure_rolls_back_only_its_savepoint(tmp_path):
    store = database(tmp_path)
    delivered = []
    with store.transaction() as outer:
        outer.put("session", "one", b"keep", expected_revision=None)
        with pytest.raises(RuntimeError, match="inner"):
            with store.transaction() as inner:
                inner.put("tasks", "one", b"rollback", expected_revision=None)
                inner.connection.after_commit["discard"] = lambda: delivered.append("wrong")
                raise RuntimeError("inner")
        assert outer.get("tasks", "one") is None
    assert delivered == []
    with store.transaction() as tx:
        assert tx.get("session", "one").payload == b"keep"


def test_outer_runtime_failure_rolls_back_successful_nested_store(tmp_path):
    store = database(tmp_path)
    with pytest.raises(RuntimeError, match="outer"):
        with store.transaction():
            with store.transaction() as inner:
                inner.put("session", "one", b"rollback", expected_revision=None)
            raise RuntimeError("outer")
    with store.transaction() as tx:
        assert tx.get("session", "one") is None

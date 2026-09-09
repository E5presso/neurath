"""Real legacy SQLite imports and cross-domain transaction boundaries."""
import sqlite3

import pytest

from neurath.runtime.database import LegacyStateChanged, LegacyTableCollision, RuntimeDatabase

pytest_plugins = ["tests.test_messaging"]


def legacy(root, component="memory", filename="project.sqlite3"):
    path = root / ".neurath/local" / component / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def test_legacy_tables_preserve_rowids_sequences_indexes_and_foreign_keys(tmp_path):
    path = legacy(tmp_path)
    with sqlite3.connect(path) as old:
        old.executescript("""
            CREATE TABLE parent(id INTEGER PRIMARY KEY AUTOINCREMENT, value BLOB);
            CREATE TABLE child(id INTEGER PRIMARY KEY, parent_id REFERENCES parent(id));
            CREATE INDEX child_parent ON child(parent_id);
            INSERT INTO parent VALUES(7,X'00ff');
            INSERT INTO parent VALUES(19,X'01');
            DELETE FROM parent WHERE id=19;
            INSERT INTO child VALUES(8,7);
        """)
    store = RuntimeDatabase(tmp_path)
    with store.connection() as db:
        assert tuple(db.execute("SELECT * FROM parent").fetchone()) == (7, b"\x00\xff")
        assert db.execute("SELECT parent_id FROM child").fetchone()[0] == 7
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        db.execute("INSERT INTO parent(value) VALUES(?)", (b"new",))
        assert db.execute("SELECT max(id) FROM parent").fetchone()[0] == 20
        assert db.execute("SELECT 1 FROM sqlite_schema WHERE name='child_parent'").fetchone()
    with sqlite3.connect(path) as old:
        assert old.execute("SELECT count(*) FROM parent").fetchone()[0] == 1


def test_wal_legacy_import_preserves_committed_rows(tmp_path):
    path = legacy(tmp_path)
    old = sqlite3.connect(path)
    try:
        old.execute("PRAGMA journal_mode=WAL")
        old.execute("CREATE TABLE wal_data(value)")
        old.execute("INSERT INTO wal_data VALUES('committed')")
        old.commit()
        store = RuntimeDatabase(tmp_path)
        with store.connection() as db:
            assert db.execute("SELECT value FROM wal_data").fetchone()[0] == "committed"
    finally:
        old.close()
    # A WAL checkpoint is explicit metadata drift, not permission to import new rows.
    store.revalidate_legacy()
    with store.connection() as db:
        assert db.execute("SELECT value FROM wal_data").fetchone()[0] == "committed"


def test_legacy_collision_rolls_back_entire_import(tmp_path):
    for component, filename in (("memory", "project.sqlite3"), ("agents", "messages.sqlite3")):
        with sqlite3.connect(legacy(tmp_path, component, filename)) as db:
            db.execute("CREATE TABLE collision(value)")
    with pytest.raises(LegacyTableCollision):
        RuntimeDatabase(tmp_path)
    with sqlite3.connect(tmp_path / ".neurath/local/runtime.sqlite3") as db:
        assert not db.execute("SELECT 1 FROM sqlite_schema WHERE name='collision'").fetchone()


def test_late_legacy_writer_is_rejected_across_database_instances(tmp_path):
    store = RuntimeDatabase(tmp_path)
    with sqlite3.connect(legacy(tmp_path)) as db:
        db.execute("CREATE TABLE late(value)")
    with pytest.raises(LegacyStateChanged):
        RuntimeDatabase(tmp_path)
    with pytest.raises(LegacyStateChanged):
        with store.connection():
            pytest.fail("late legacy writer accepted")


def test_legacy_revalidation_accepts_only_logically_identical_changes(tmp_path):
    path = legacy(tmp_path)
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE original(value)")
        db.execute("INSERT INTO original VALUES(1)")
    store = RuntimeDatabase(tmp_path)
    path.touch()
    with pytest.raises(LegacyStateChanged):
        with store.connection():
            pass
    store.revalidate_legacy()
    with store.connection() as db:
        assert db.execute("SELECT value FROM original").fetchone()[0] == 1
    with sqlite3.connect(path) as db:
        db.execute("UPDATE original SET value=2")
    with pytest.raises(LegacyStateChanged):
        store.revalidate_legacy()


def test_message_and_task_records_share_outer_rollback_and_notifications(peers, monkeypatch):
    from neurath.agents import delivery

    store, sender, recipient, _ = peers
    notices = []
    monkeypatch.setattr(delivery, "dispatch", lambda _store, message: notices.append(message))
    with pytest.raises(RuntimeError, match="abort"):
        with store.database.transaction() as tx:
            tx.put("fixture-tasks", "one", b"pending", expected_revision=None)
            store.send_many(sender, [{"key": "atomic-task", "message": "Work", "to": [recipient]}])
            assert notices == []
            raise RuntimeError("abort")
    assert store.inbox(recipient) == []
    assert notices == []
    with store.database.transaction() as tx:
        assert tx.get("fixture-tasks", "one") is None

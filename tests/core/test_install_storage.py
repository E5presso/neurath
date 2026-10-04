"""Installer history moves to the core store without changing old data or atomicity."""

import json
import sqlite3
import subprocess

import pytest

from neurath.install.state_store import InstallStateStore, digest


def repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    return tmp_path


def test_new_installation_metadata_uses_core_database(tmp_path):
    store = InstallStateStore(repo(tmp_path), create=True)
    assert store.path == tmp_path / ".neurath/local/core.sqlite3"
    store.ensure_state({"installed": "current"})
    assert store.state() == {"installed": "current"}


def test_old_installation_history_is_copied_without_rewriting_original(tmp_path):
    root = repo(tmp_path)
    local = root / ".neurath/local"
    local.mkdir(parents=True)
    old = local / "runtime.sqlite3"
    state = {"installed": "previous"}
    with sqlite3.connect(old) as db:
        db.execute(
            "CREATE TABLE installation_states(root TEXT PRIMARY KEY,digest TEXT NOT NULL,payload TEXT NOT NULL,updated REAL NOT NULL)"
        )
        db.execute(
            "INSERT INTO installation_states VALUES(?,?,?,?)",
            (str(root), digest(state), json.dumps(state), 1.0),
        )
    original = old.read_bytes()
    store = InstallStateStore(root)
    assert store.state() == state
    assert old.read_bytes() == original
    assert store.path.name == "core.sqlite3"
    assert not store.path.exists()
    assert InstallStateStore(root, create=True).state() == state
    assert store.path.exists()


def test_failed_installer_finish_rolls_back_receipt_state_and_journal_together(tmp_path):
    root = repo(tmp_path)
    store = InstallStateStore(root, create=True)
    store.ensure_state({"installed": "old"})
    plan = {"root": str(root), "action": "install"}
    plan["id"] = digest(plan)
    store.begin(plan)
    with store.database.sql_transaction() as db:
        db.execute(
            "CREATE TRIGGER fail_state BEFORE UPDATE ON installation_states BEGIN SELECT RAISE(ABORT,'test rollback'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="test rollback"):
        store.finish(plan, {"installed": "new"})
    assert store.state() == {"installed": "old"}
    assert store.receipt(plan["id"]) is None
    assert store.journal() == plan


def test_reporting_runtime_record_migrates_without_changing_consent_or_source(tmp_path):
    from hashlib import sha256

    from neurath.reporting import Reporting

    root = repo(tmp_path)
    local = root / ".neurath/local"
    local.mkdir(parents=True)
    old = local / "runtime.sqlite3"
    value = {"schema": 1, "auto_report": False, "reports": {}}
    raw = json.dumps(value).encode()
    key = ".git/neurath-reporting/state.json"
    with sqlite3.connect(old) as db:
        db.execute(
            "CREATE TABLE runtime_records(namespace TEXT,key TEXT,payload BLOB,digest TEXT,legacy_path TEXT,legacy_digest TEXT)"
        )
        db.execute(
            "INSERT INTO runtime_records VALUES(?,?,?,?,?,?)",
            ("reporting", key, raw, sha256(raw).hexdigest(), None, None),
        )
    original = old.read_bytes()
    assert Reporting(root).status()["auto_report"] is False
    assert old.read_bytes() == original


def test_unseen_legacy_consent_cannot_be_overwritten_by_stale_default_snapshot(tmp_path):
    from neurath.core.domain import CoreError
    from neurath.reporting import Reporting

    service = Reporting(repo(tmp_path))
    snapshot = service._read()
    service.directory.mkdir()
    service.path.write_text(json.dumps({"schema": 1, "auto_report": False, "reports": {}}))
    snapshot["auto_report"] = True
    with pytest.raises(CoreError, match="service-source-changed"):
        service._save(snapshot)
    assert service.status()["auto_report"] is False

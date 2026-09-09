"""Installation and maintenance cutovers preserve recovery and reject foreign paths."""
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest


def maintenance():
    from neurath.runtime.engine import activate
    activate()
    from scripts.agent_harness.harness_maintenance import HarnessMaintenanceStore, HarnessMaintenanceError
    return HarnessMaintenanceStore, HarnessMaintenanceError


def lease():
    now = datetime.now(timezone.utc)
    return {"schema_version": 1, "lease_id": "a" * 32, "status": "active",
            "session_id": "one", "actor_id": "owner", "reason": "Fixture maintenance",
            "targets": ["/fixture/AGENTS.md"], "opened_at": now.isoformat(),
            "expires_at": (now + timedelta(seconds=300)).isoformat()}


def test_maintenance_cutover_concurrent_import_preserves_one_lease(tmp_path):
    store_type, _ = maintenance()
    path = tmp_path / ".agents/runs/one/harness-maintenance.json"
    path.parent.mkdir(parents=True)
    expected = lease()
    path.write_text(json.dumps(expected))
    with ThreadPoolExecutor(max_workers=2) as pool:
        stores = list(pool.map(lambda _: store_type(tmp_path), range(2)))
    assert not path.exists()
    assert stores[0].read_active("one") == expected
    with stores[0].database.connection() as db:
        assert db.execute("SELECT count(*) FROM harness_maintenance_leases").fetchone()[0] == 1
        assert db.execute("SELECT status FROM harness_maintenance_legacy_files").fetchone()[0] == "removed"


def test_interrupted_legacy_close_imports_receipt_without_reviving_lease(tmp_path):
    store_type, error = maintenance()
    original = lease()
    closed = {**original, "status": "closed", "closed_at": datetime.now(timezone.utc).isoformat(),
              "summary": "Interrupted after receipt write", "readback": [{"target": original["targets"][0],
                                                                          "state": "missing", "sha256": None}]}
    path = tmp_path / ".agents/runs/one/harness-maintenance.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(closed))
    store = store_type(tmp_path)
    assert not path.exists()
    with pytest.raises(error, match="no active"):
        store.read_active("one")
    with store.database.connection() as db:
        assert json.loads(db.execute("SELECT payload FROM harness_maintenance_receipts").fetchone()[0]) == closed


def test_maintenance_foreign_path_and_invalid_schema_preserve_source(tmp_path):
    store_type, error = maintenance()
    path = tmp_path / ".agents/runs/other/harness-maintenance.json"
    path.parent.mkdir(parents=True)
    original = json.dumps(lease())
    path.write_text(original)
    with pytest.raises(error, match="pathname"):
        store_type(tmp_path)
    assert path.read_text() == original
    malformed = lease()
    malformed.pop("targets")
    path.write_text(json.dumps(malformed))
    with pytest.raises(error, match="schema"):
        store_type(tmp_path)
    assert json.loads(path.read_text()) == malformed


def test_maintenance_close_is_atomic_and_legacy_reappearance_fails(tmp_path):
    store_type, error = maintenance()
    store = store_type(tmp_path)
    original = lease()
    store.begin(original)
    closed = {**original, "status": "closed", "closed_at": datetime.now(timezone.utc).isoformat(),
              "summary": "Verified fixture", "readback": [{"target": original["targets"][0],
                                                             "state": "missing", "sha256": None}]}
    assert store.close(original, closed).endswith(original["lease_id"])
    with pytest.raises(error, match="no active"):
        store.read_active("one")
    with store.database.connection() as db:
        assert json.loads(db.execute("SELECT payload FROM harness_maintenance_receipts").fetchone()[0]) == closed
    path = tmp_path / ".agents/runs/one/harness-maintenance.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(original))
    with pytest.raises(error, match="after SQLite cutover"):
        store_type(tmp_path)
    assert path.exists()


def test_legacy_install_journal_recovers_before_sqlite_cutover(tmp_path):
    from neurath.install import transaction as installer
    from neurath.install.state_store import InstallStateStore
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    plan = installer.make_plan(tmp_path)
    legacy = installer.git_dir(tmp_path) / "neurath-journal.json"
    installer._save_json(legacy, plan)
    first = plan["changes"][0]
    installer._write(tmp_path, first["path"], first["after"])
    assert installer.recover(tmp_path)["recovered"]
    assert installer.snapshot(tmp_path, first["path"]) == first["before"]
    assert not legacy.exists()
    assert InstallStateStore(tmp_path).journal() is None


def test_install_state_projection_is_reference_and_receipt_is_durable(tmp_path):
    from neurath.install import transaction as installer
    from neurath.install.state_store import InstallStateStore
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    plan = installer.make_plan(tmp_path)
    installer.apply_plan(tmp_path, plan)
    visible = json.loads((tmp_path / ".neurath/install.json").read_text())
    assert visible["schema"] == 2 and visible["authority"] == "reference-only"
    store = InstallStateStore(tmp_path)
    assert store.state() == installer.read_state(tmp_path)
    assert store.receipt(plan["id"]) == plan
    assert not list((tmp_path / ".git/neurath-receipts").glob("*.json"))
    visible["digest"] = "0" * 64
    (tmp_path / ".neurath/install.json").write_text(json.dumps(visible))
    with pytest.raises(installer.InstallError, match="reference mismatch"):
        installer.read_state(tmp_path)

"""Service snapshots preserve consent, worktree scope, and optimistic revision."""
import json
import subprocess

import pytest

from neurath.reporting import Reporting
from neurath.updates import Updates
from neurath.runtime.database import LegacyStateChanged, RecordConflict


def project(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    return root


def test_reporting_import_preserves_consent_without_new_json_writes(tmp_path):
    root = project(tmp_path)
    service = Reporting(root)
    service.directory.mkdir()
    raw = '{"schema":1,"auto_report":true,"reports":{}}'
    service.path.write_text(raw)
    assert service.status()["auto_report"] is True
    service.consent(False)
    assert Reporting(root).status()["auto_report"] is False
    assert service.path.read_text() == raw
    service.path.write_text(raw.replace("true", "false"))
    with pytest.raises(LegacyStateChanged):
        service.status()


def test_local_state_rejects_stale_snapshot_without_lost_update(tmp_path):
    service = Reporting(project(tmp_path))
    a, b = service._read(), service._read()
    a["auto_report"] = True
    service._save(a)
    b["auto_report"] = False
    with pytest.raises(RecordConflict):
        service._save(b)
    assert service.status()["auto_report"] is True
    assert not service.path.exists()


def test_update_state_roundtrip_uses_db_and_preserves_size_validation(tmp_path):
    service = Updates(project(tmp_path))
    state = service._read()
    state["checked"] = 123
    service._save(state)
    assert Updates(service.root)._read()["checked"] == 123
    assert not service.path.exists()
    state["oversized"] = "x" * (2 * 1024 * 1024)
    with pytest.raises(ValueError, match="limit"):
        service._save(state)


def test_reporting_shared_but_update_choices_scoped_to_worktree(tmp_path):
    root = project(tmp_path)
    subprocess.run(["git", "-C", str(root), "-c", "user.name=Test", "-c",
                    "user.email=test@example.invalid", "commit", "--allow-empty", "-qm", "initial"], check=True)
    other = tmp_path / "other"
    subprocess.run(["git", "-C", str(root), "worktree", "add", "-qb", "other", str(other)], check=True)
    Reporting(root).consent(True)
    assert Reporting(other).status()["auto_report"] is True
    original = Updates(root)
    state = original._read()
    state["choices"]["1.0.0"] = {"decision": "later"}
    original._save(state)
    assert Updates(other)._read()["choices"] == {}
    assert Updates(root)._read()["choices"] == {"1.0.0": {"decision": "later"}}

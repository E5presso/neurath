"""Legacy installation bytes may become references without weakening recovery checks."""
import hashlib
import json
import subprocess
from copy import deepcopy

import pytest


@pytest.fixture
def legacy_upgrade(tmp_path, monkeypatch):
    from neurath.install import transaction as installer
    root = tmp_path / "project"
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    # Materialize the exact pre-SQLite installation/receipt format as fixture data.
    legacy = installer.make_plan(root, hosts=["codex"])
    original_state = legacy["after_state"]
    for entry in legacy["changes"]:
        if entry["path"] == installer.STATE:
            entry["after"] = installer.file_value(
                (installer.canonical(original_state) + "\n").encode(), 0o600)
    legacy.pop("before_state")
    legacy.pop("after_state")
    legacy.pop("id")
    legacy["id"] = hashlib.sha256(installer.canonical(legacy).encode()).hexdigest()
    for entry in legacy["changes"]:
        installer._write(root, entry["path"], entry["after"])
    installer._save_json(installer.git_dir(root) / "neurath-receipts" / (legacy["id"] + ".json"), legacy)
    assert installer.read_state(root) == original_state
    monkeypatch.setattr(installer, "__version__", "0.2.0")
    update = installer.make_plan(root, action="update")
    directory = tmp_path / "updates"
    stage = directory / "candidate-fixture"
    stage.mkdir(parents=True)
    (stage / "plan.json").write_text(installer.canonical(update))
    operation = {"stage": stage.name, "plan_id": update["id"], "distribution": update["distribution"]}
    return root, legacy, original_state, update, directory, operation


def test_first_sqlite_update_recovers_legacy_state_and_retains_legacy_restore(legacy_upgrade, monkeypatch):
    from neurath import release_install
    from neurath.install import transaction as installer
    root, legacy, before, update, directory, operation = legacy_upgrade
    installer.apply_plan(root, update)
    calls = []
    def runtime(_python, target, *args):
        calls.append(args[0])
        assert args == ("restore", update["id"])
        return installer.apply_plan(target, installer.make_plan(target, action="restore", receipt=args[1]))
    monkeypatch.setattr(release_install, "runtime_command", runtime)
    assert release_install.recover(root, directory, operation) == {"phase": "recovered"}
    assert calls == ["restore"]
    assert installer.read_state(root) == before
    assert json.loads((root / installer.STATE).read_text())["schema"] == 2
    for entry in update["changes"]:
        if entry["path"] != installer.STATE:
            assert installer.snapshot(root, entry["path"]) == entry["before"]
    # The imported pre-cutover receipt remains usable after schema-2 rollback.
    undo = installer.make_plan(root, action="restore", receipt=legacy["id"])
    installer.apply_plan(root, undo)
    assert installer.read_state(root) is None


def test_semantic_state_comparison_rejects_changed_permissions_and_forged_state(legacy_upgrade):
    from neurath.install import transaction as installer
    root, _legacy, before, update, _directory, _operation = legacy_upgrade
    expected = next(entry["before"] for entry in update["changes"] if entry["path"] == installer.STATE)
    installer.apply_plan(root, update)
    installer.apply_plan(root, installer.make_plan(root, action="restore", receipt=update["id"]))
    assert installer.installation_state_matches(root, expected, expected_state=before)
    forged = deepcopy(before)
    forged["version"] = "different"
    with pytest.raises(installer.InstallError, match="expected canonical state"):
        installer.installation_state_matches(root, expected, expected_state=forged)
    (root / installer.STATE).chmod(0o644)
    assert not installer.installation_state_matches(root, expected, expected_state=before)


def test_release_recovery_keeps_nonstate_file_bytes_exact(legacy_upgrade):
    from neurath import release_install
    from neurath.install import transaction as installer
    root, _legacy, _before, update, _directory, _operation = legacy_upgrade
    (root / "user-file").write_bytes(b"changed")
    sample = deepcopy(update)
    sample["changes"].append({"path": "user-file", "before": installer.file_value(b"original"),
                               "after": installer.file_value(b"updated")})
    assert not release_install._matches_plan_files(root, sample, "before")


def test_release_detects_changed_canonical_contribution_approval(legacy_upgrade, monkeypatch):
    from neurath import release_install
    from neurath.install import transaction as installer
    from neurath.reporting import Reporting
    root, _legacy, _before, update, directory, operation = legacy_upgrade
    reporting = Reporting(root)
    state = reporting._read()
    state["auto_report"] = True
    state["reports"] = {"fixture-draft": {"approved": True}}
    reporting._save(state)
    # The legacy path cannot prove the canonical per-draft approval survived.
    legacy_before = reporting.path.read_bytes() if reporting.path.exists() else None
    monkeypatch.setattr(release_install, "verify", lambda *_args: update["distribution"])
    monkeypatch.setattr("neurath.doctor.passed", lambda _report: True)
    def runtime(_python, target, *args):
        if args[0] == "apply":
            receipt = installer.apply_plan(target, update)
            altered = Reporting(target)._read()
            altered["reports"]["fixture-draft"]["approved"] = False
            Reporting(target)._save(altered)
            return receipt
        assert args == ("doctor", "--protocol")
        return {}
    monkeypatch.setattr(release_install, "runtime_command", runtime)
    with pytest.raises(ValueError, match="reporting preferences changed"):
        release_install.apply(root, directory, {"version": "0.2.0"}, operation)
    assert (reporting.path.read_bytes() if reporting.path.exists() else None) == legacy_before

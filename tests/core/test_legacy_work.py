"""Offline adoption keeps original goals/ownership and never invents fresh evidence."""

import json
import sqlite3
from hashlib import sha256

import pytest

from neurath.core.domain import CoreError, stop_reasons
from neurath.core.legacy_work import adopt, preview, snapshot
from neurath.core.store import Store


def legacy(root, *, failed=False):
    local = root / ".neurath/local"
    local.mkdir(parents=True)
    path = local / "runtime.sqlite3"
    rows = {
        ("task-ledger", "session"): {
            "schema": "neurath.task-ledger.v1",
            "session": "session",
            "owner": "codex:session:session",
            "tasks": [
                {
                    "id": "prior",
                    "status": "succeeded",
                    "revision": 3,
                    "definition": {
                        "goal": "Prerequisite delivered",
                        "acceptance": ["Prerequisite exists"],
                        "dependencies": [],
                    },
                },
                {
                    "id": "unfinished",
                    "status": "failed" if failed else "in_progress",
                    "revision": 2,
                    "definition": {
                        "goal": "Deliver the original user result",
                        "acceptance": ["Original result works"],
                        "dependencies": ["prior"],
                    },
                },
            ],
        },
        ("worktree", "checkout"): {
            "current": {"path": str(root), "actor_id": "codex:session:session", "lease_epoch": 7}
        },
    }
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE runtime_records(namespace TEXT,key TEXT,revision INTEGER,payload BLOB,digest TEXT,updated REAL,legacy_path TEXT,legacy_digest TEXT,PRIMARY KEY(namespace,key))"
        )
        for (namespace, key), value in rows.items():
            payload = json.dumps(value).encode()
            db.execute(
                "INSERT INTO runtime_records VALUES(?,?,?,?,?,0,NULL,NULL)",
                (namespace, key, 1, payload, sha256(payload).hexdigest()),
            )
    return path


@pytest.mark.parametrize("failed", [False, True])
def test_adoption_preserves_unfinished_goal_dependencies_and_writer_without_activating_actor(
    tmp_path, failed
):
    path = legacy(tmp_path, failed=failed)
    before = path.read_bytes()
    document = snapshot(tmp_path)
    assert preview(document)["task_ids"] == ["unfinished"]
    store = Store(tmp_path)
    result = adopt(store, expected_digest=document["digest"])
    assert result["task_ids"] == ["unfinished"]
    assert path.read_bytes() == before
    with store.transaction() as tx:
        task = tx.task("unfinished")
        assert task.goal == "Deliver the original user result"
        assert task.state == "waiting" and task.dependencies == ("prior",)
        assert task.revision > 2
        assert tx.task("prior").state == "completed"
        assert stop_reasons("session", "codex:session:session", tx.tasks())
        assert tx.lease(str(tmp_path)) == {
            "checkout": str(tmp_path),
            "writer": "codex:session:session",
            "generation": 8,
        }
        assert tx.record("actor", "codex:session:session") is None
        assert tx.source(task.instruction_sources[0]).kind == "report"
    assert adopt(store, expected_digest=document["digest"]) == result


def test_changed_source_or_existing_destination_is_not_overwritten(tmp_path):
    path = legacy(tmp_path)
    document = snapshot(tmp_path)
    store = Store(tmp_path)
    with pytest.raises(CoreError, match="legacy-work-source-changed"):
        adopt(store, expected_digest="different")
    with sqlite3.connect(path) as db:
        db.execute("UPDATE runtime_records SET payload=? WHERE namespace='task-ledger'", (b"{}",))
    with pytest.raises(CoreError, match="legacy-work-corrupt"):
        adopt(store, expected_digest=document["digest"])
    with store.transaction() as tx:
        assert not tx.tasks() and tx.lease(str(tmp_path)) is None


def test_only_matching_original_text_restores_imported_prompt_provenance(tmp_path):
    from neurath.core.commands import Context
    from neurath.core.service import Core

    path = legacy(tmp_path)
    original = "Continue the original work and release the verified result."
    proof = {
        "actor_id": "codex:session:session",
        "authority_reference": "user-prompt:retained",
        "prompt_digest": sha256(original.encode()).hexdigest(),
    }
    payload = json.dumps(proof).encode()
    with sqlite3.connect(path) as db:
        db.execute(
            "INSERT INTO runtime_records VALUES(?,?,?,?,?,0,NULL,NULL)",
            ("prompt:session", "user-prompt:retained", 1, payload, sha256(payload).hexdigest()),
        )
    core = Core(tmp_path)
    adopt(core.store, expected_digest=snapshot(tmp_path)["digest"])
    core.sessions.observe_actor("codex:session:session", "session", "codex")
    context = Context("codex:session:session", "session", "native-restoration")
    with core.store.transaction() as tx:
        source_id = tx.records("legacy-prompt")[0]["id"]
    fields = {"task_id": "unfinished", "source_id": source_id}
    with pytest.raises(CoreError, match="source-changed"):
        core.call(
            context,
            "source_restore",
            {"key": "invented", **fields, "body": "Approve unrelated publication."},
        )
    restored = core.call(context, "source_restore", {"key": "restore", **fields, "body": original})[
        "source"
    ]
    assert restored["kind"] == "native_input" and restored["text"] == original
    assert (
        core.call(context, "source_read", {"source_id": restored["id"]})["origin"]["value"][
            "origin"
        ]
        == "unknown"
    )


def test_installer_plan_is_readonly_and_apply_adopts_original_obligations(tmp_path):
    import subprocess

    from neurath.install.transaction import apply_plan, make_plan

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    old = legacy(tmp_path)
    original = old.read_bytes()
    plan = make_plan(tmp_path)
    assert plan["core_transition"]["task_ids"] == ["unfinished"]
    assert not (tmp_path / ".neurath/local/core.sqlite3").exists()
    apply_plan(tmp_path, plan)
    assert old.read_bytes() == original
    with Store(tmp_path).transaction() as tx:
        assert tx.task("unfinished").state == "waiting"
        assert tx.lease(str(tmp_path))["writer"] == "codex:session:session"
    assert make_plan(tmp_path)["changes"] == []


def test_installer_blocks_live_old_host_before_adoption_or_file_changes(tmp_path, monkeypatch):
    import subprocess

    from neurath.install import transition
    from neurath.install.transaction import apply_plan, make_plan

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    legacy(tmp_path)
    plan = make_plan(tmp_path)
    original = transition._require_offline

    def live(*args):
        raise CoreError("core-transition-host-active", process_ids=[123])

    monkeypatch.setattr(transition, "_require_offline", live)
    with pytest.raises(CoreError, match="core-transition-host-active"):
        apply_plan(tmp_path, plan)
    assert not (tmp_path / ".neurath/local/core.sqlite3").exists()
    assert not (tmp_path / "AGENTS.md").exists()
    monkeypatch.setattr(transition, "_require_offline", original)
    apply_plan(tmp_path, plan)


def test_historical_v1_changes_do_not_become_a_second_progress_gate_after_adoption(tmp_path):
    import subprocess

    from neurath.install.transaction import apply_plan, make_plan

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    old = legacy(tmp_path)
    apply_plan(tmp_path, make_plan(tmp_path))
    old.rename(old.with_suffix(".archive"))
    assert make_plan(tmp_path)["changes"] == []


def test_transition_detects_same_project_host_from_linked_checkout(tmp_path, monkeypatch):
    import subprocess
    from contextlib import ExitStack

    from neurath.install import transition

    root, linked = tmp_path / "main", tmp_path / "linked checkout"
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "--allow-empty",
            "-qm",
            "fixture",
        ],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(root), "worktree", "add", "-q", "--detach", str(linked)], check=True
    )
    original = transition.subprocess.run

    def observe(argv, **kwargs):
        if argv[:2] == ["/bin/ps", "-axo"]:
            return subprocess.CompletedProcess(
                argv, 0, stdout=f"123 python -I -m neurath.agents.mcp --root {linked}\n"
            )
        return original(argv, **kwargs)

    monkeypatch.setattr(transition.subprocess, "run", observe)
    with sqlite3.connect(":memory:") as db, ExitStack() as stack:
        with pytest.raises(CoreError, match="core-transition-host-active"):
            transition._require_offline(root.resolve(), db, stack)

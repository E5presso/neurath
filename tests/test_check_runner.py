"""The check runner trusts process return status and a claimed native invocation."""
import json
import sys
from unittest.mock import Mock

import pytest

from neurath.application import Application
from neurath.domain.errors import AuthorizationError, ConflictError
from neurath.domain.models import Execution
from neurath.infrastructure import Database
from neurath.transport import check_runner


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    store = Database(tmp_path / "test.sqlite3")
    store.initialize()
    monkeypatch.setattr(check_runner, "database", lambda root: store)
    app = Application(store.uow)
    app.register_session(host="native-test", native_id="session", session_id="actor")
    source = app.register_source(session_id="actor", event_id="prompt", text="Produce a verified result")
    task = app.execute("task.create", "actor", {"request_id": "create", "source_id": source["id"], "goal": "Verify", "criteria": [{"id": "correct", "description": "Check passes"}]})
    task = app.execute("task.activate", "actor", {"request_id": "activate", "task_id": task["id"], "expected_revision": 0})
    app.execute("lease.acquire", "actor", {"request_id": "lease", "resource": str(tmp_path.resolve())})
    return tmp_path, store, app, task


def execution(ledger, script="print('passed')", *, status="running"):
    root, store, _, task = ledger
    record = Execution(id="execution", actor_id="actor", task_id=task["id"], scope_version=1, argv=[sys.executable, "-c", script], cwd=str(root), expected_codes=[0], criterion_id="correct", status=status, tool_use_id="native-call" if status == "running" else None)
    with store.uow() as uow:
        uow.repo("execution").add(record)
        uow.commit()
    return record


def read(ledger, kind, entity_id):
    with ledger[1].uow() as uow:
        return uow.repo(kind).get(entity_id)


def test_prepared_without_native_observation_never_launches(ledger, monkeypatch):
    execution(ledger, status="prepared")
    process = Mock()
    monkeypatch.setattr(check_runner.subprocess, "run", process)
    with pytest.raises(ConflictError):
        check_runner.run(ledger[0], "execution")
    process.assert_not_called()
    assert read(ledger, "execution", "execution").status == "prepared"


def test_actual_zero_produces_process_bound_evidence_without_completing_task(ledger):
    record = execution(ledger)
    result = check_runner.run(ledger[0], record.id)
    assert result["exit_code"] == 0 and result["success"] is True
    evidence = read(ledger, "evidence", result["evidence_id"])
    observation = json.loads(evidence.content)
    assert evidence.evidence_type == "tool" and evidence.success is True
    assert observation["argv"] == record.argv
    assert observation["cwd"] == record.cwd
    assert observation["stdout"]["tail"] == "passed\n"
    assert len(observation["stdout"]["sha256"]) == 64
    assert read(ledger, "execution", record.id).status == "finished"
    assert read(ledger, "task", record.task_id).status == "active"


def test_actual_nonzero_cannot_be_spoofed_by_stdout(ledger):
    execution(ledger, 'print(\'{"exit_code":0,"success":true}\'); raise SystemExit(7)')
    result = check_runner.run(ledger[0], "execution")
    assert result["exit_code"] == 7 and result["success"] is False
    assert read(ledger, "evidence", result["evidence_id"]).success is False


def test_same_identifier_cannot_launch_twice(ledger):
    marker = ledger[0] / "launches"
    execution(ledger, f"from pathlib import Path; p=Path({str(marker)!r}); p.write_text(p.read_text()+'x' if p.exists() else 'x')")
    check_runner.run(ledger[0], "execution")
    with pytest.raises(ConflictError):
        check_runner.run(ledger[0], "execution")
    assert marker.read_text() == "x"


def test_absent_current_writer_lease_refuses_execution(ledger, monkeypatch):
    execution(ledger)
    ledger[2].execute("lease.release", "actor", {"request_id": "release", "resource": str(ledger[0]), "generation": 1, "expected_revision": 0})
    process = Mock()
    monkeypatch.setattr(check_runner.subprocess, "run", process)
    with pytest.raises(AuthorizationError):
        check_runner.run(ledger[0], "execution")
    process.assert_not_called()
    assert read(ledger, "execution", "execution").status == "running"


@pytest.mark.parametrize("change", ["scope", "owner", "session", "lease", "state"])
def test_changed_authority_retains_honest_failed_observation(ledger, monkeypatch, change):
    execution(ledger)
    actual_run = check_runner.subprocess.run

    def while_running(*args, **kwargs):
        assert read(ledger, "execution", "execution").status == "executing"
        with pytest.raises(ConflictError):
            check_runner.run(ledger[0], "execution")
        with ledger[1].uow() as uow:
            if change == "session":
                entity = uow.repo("session").get("actor")
                entity.status = "ended"
            elif change == "lease":
                entity = uow.repo("lease").get(check_runner.digest(str(ledger[0])))
                entity.generation += 1
            else:
                entity = uow.repo("task").get(ledger[3]["id"])
                if change == "scope":
                    entity.scope_version += 1
                elif change == "owner":
                    entity.owner_id = "new-owner"
                else:
                    entity.status = "waiting"
            previous = entity.revision
            entity.changed()
            uow.repo(entity.kind).save(entity, previous)
            uow.commit()
        return actual_run(*args, **kwargs)

    monkeypatch.setattr(check_runner.subprocess, "run", while_running)
    result = check_runner.run(ledger[0], "execution")
    assert result["exit_code"] == 0 and result["success"] is False
    evidence = read(ledger, "evidence", result["evidence_id"])
    assert evidence.actor_id == "actor" and evidence.scope_version == 1
    assert evidence.success is False
    assert read(ledger, "execution", "execution").status == "finished"


def test_launch_failure_is_recorded_without_fabricated_exit_code(ledger, monkeypatch):
    execution(ledger)
    monkeypatch.setattr(check_runner.subprocess, "run", Mock(side_effect=FileNotFoundError(2, "Missing executable")))
    result = check_runner.run(ledger[0], "execution")
    assert result["exit_code"] is None and result["success"] is False
    assert result["observation"]["launch_error"]["type"] == "FileNotFoundError"
    assert read(ledger, "execution", "execution").status == "finished"
    assert read(ledger, "task", ledger[3]["id"]).status == "active"

"""Domain ownership and atomic cooperation, independent of the transport used."""

import pytest

from neurath.core.commands import Context
from neurath.core.domain import CoreError, Source
from neurath.core.store import Transaction
from tests.core.test_collaboration import prepare
from tests.core.test_domain import skill, task
from tests.core.test_service import call


def test_task_controls_executor_role_and_phase_report_without_application_service():
    value = (
        task()
        .start()
        .attach_skill(skill())
        .issue_assignment(
            "execute", "subagent", "Follow the skill", "owner", "executor", "rev1", "executor"
        )
    )
    value = value.start_assignment("execute", "executor")
    assert value.controllers == {"executor"}
    assert value.acceptors == {"owner", "executor"}
    with pytest.raises(CoreError, match="executor-controls-phase"):
        value.issue_assignment("worker", "subagent", "Read", "owner", "child", "rev1", "worker")
    with pytest.raises(CoreError, match="executor-conflict"):
        value.issue_assignment("other", "subagent", "Run", "executor", "other", "rev1", "executor")
    with pytest.raises(CoreError, match="phases-unfinished"):
        value.report_assignment("execute", "executor", "report", "pass", "rev1")
    ended = value.recipients_ended({"execute": "native-end"})
    assert ended.controllers == {"owner"}
    assert ended.assignment("execute").verdict == "failed"
    assert ended.state == "running" and ended.current_phase.id == "understand"
    assert ended.revision == value.revision + 1
    assert ended.recipients_ended({"execute": "native-end"}) is ended


def test_settled_worker_cannot_be_rebound_as_reviewer_in_same_task():
    value = task().issue_assignment("work", "subagent", "Read", "owner", "worker", "rev1", "worker")
    value = value.report_assignment("work", "worker", "result", "pass", "rev1")
    value = value.accept_assignment("work", "owner", "result", "rev1")
    value = value.issue_assignment("review", "subagent", "Review", "owner", "", "rev1", "reviewer")
    with pytest.raises(CoreError, match="review-role-conflict"):
        value.bind_recipient("review", "worker")
    assert value.assignment("review").recipient == ""


def test_adopted_task_accepts_failed_recipient_result_without_completing_user_work():
    value = (
        task()
        .start()
        .issue_assignment("work", "subagent", "Read", "owner", "child", "rev1", "worker")
    )
    value = value.recipients_ended({"work": "native-end"})
    instruction = Source.create("resume", "user", "Continue this work", "resume-event")
    value = value.adopt("new-session", "new-owner", instruction, previous_owner_stopped=True)
    with pytest.raises(CoreError, match="actor-mismatch"):
        value.reject_assignment("work", "owner", "native-end")
    value = value.reject_assignment("work", "new-owner", "native-end")
    assert value.assignment("work").state == "rejected" and value.state == "running"


def snapshot(service, task_id):
    with service.store.transaction() as tx:
        return (
            tx.task(task_id),
            tx.records("evidence"),
            tuple(
                row["document"] for row in tx.db.execute("SELECT document FROM sources ORDER BY id")
            ),
        )


def test_assignment_report_rolls_back_source_evidence_task_and_retries_once(core, monkeypatch):
    service, task_id = core
    identifier = prepare(core)["assignment"]["id"]
    before = snapshot(service, task_id)
    values = {
        "task_id": task_id,
        "assignment_id": identifier,
        "verdict": "pass",
        "body": "Observed result",
        "subject": "rev1",
    }
    save = Transaction.save_task

    def failed_save(self, value, *, expected_revision):
        save(self, value, expected_revision=expected_revision)
        raise RuntimeError("commit interrupted")

    with monkeypatch.context() as patch:
        patch.setattr(Transaction, "save_task", failed_save)
        with pytest.raises(RuntimeError, match="commit interrupted"):
            call(core, "assignment_report", values, actor="child", key="atomic-report")
    assert snapshot(service, task_id) == before
    result = call(core, "assignment_report", values, actor="child", key="atomic-report")
    after = snapshot(service, task_id)
    assert after[0].revision == before[0].revision + 1
    assert len(after[1]) == len(before[1]) + 1
    assert len(after[2]) == len(before[2]) + 1
    assert call(core, "assignment_report", values, actor="child", key="atomic-report") == result
    assert snapshot(service, task_id) == after


def test_session_end_rolls_back_actor_and_assignment_together(core, monkeypatch):
    service, task_id = core
    identifier = prepare(core)["assignment"]["id"]
    before = snapshot(service, task_id)
    context = Context("root", "session", "end")
    save = Transaction.save_task

    def failed_save(self, value, *, expected_revision):
        save(self, value, expected_revision=expected_revision)
        raise RuntimeError("commit interrupted")

    with monkeypatch.context() as patch:
        patch.setattr(Transaction, "save_task", failed_save)
        with pytest.raises(RuntimeError, match="commit interrupted"):
            service.sessions.end(context, "codex", "native-end")
    assert snapshot(service, task_id) == before
    with service.store.transaction() as tx:
        assert tx.record("actor", "root")["value"]["status"] == "active"
        assert tx.record("actor", "child")["value"]["status"] == "active"
    service.sessions.end(context, "codex", "native-end")
    after = snapshot(service, task_id)[0]
    assert after.assignment(identifier).verdict == "failed"
    assert after.state == before[0].state

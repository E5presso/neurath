"""Delegated work shares a task; reporting and acceptance have different owners."""

import pytest

from neurath.core.domain import CoreError
from neurath.core.service import Context
from tests.core.test_service import call


def prepare(core, *, role="worker", actor="child", execution="subagent"):
    service, task_id = core
    task = service.call(Context("root", "session", "read"), "task_read", {"task_id": task_id})[
        "task"
    ]
    return call(
        core,
        "assignment_prepare",
        {
            "task_id": task_id,
            "expected_revision": task["revision"],
            "execution": execution,
            "reason": "Bounded work required by the task",
            "scope": "Inspect the assigned result",
            "recipient": actor,
            "subject": "rev1",
            "role": role,
            "checkout": str(service.store.root),
        },
        key="prepare-" + role + "-" + actor,
    )


def test_child_reports_without_writer_lease_and_owner_accepts_actual_result(core):
    service, task_id = core
    prepared = prepare(core, role="reviewer")
    identifier = prepared["assignment"]["id"]
    call(
        core,
        "assignment_start",
        {"task_id": task_id, "assignment_id": identifier},
        actor="child",
        key="start-child",
    )
    report = call(
        core,
        "assignment_report",
        {
            "task_id": task_id,
            "assignment_id": identifier,
            "verdict": "pass",
            "body": "Reviewed the actual fixed revision",
            "subject": "rev1",
        },
        actor="child",
        key="report-child",
    )
    assert report["assignment"]["state"] == "reported"
    assert report["evidence"]["kind"] == "review"
    assert service.stop(Context("child", "session", "child-stop"))["allowed"]
    assert not service.stop(Context("root", "session", "root-stop"))["allowed"]
    accepted = call(
        core,
        "assignment_accept",
        {
            "task_id": task_id,
            "assignment_id": identifier,
            "source_id": report["assignment"]["result_source"],
            "subject": "rev1",
        },
        key="accept",
    )
    assert accepted["assignment"]["state"] == "accepted"
    assert not service.stop(Context("root", "session", "still-unfinished"))["allowed"]


def test_another_provider_is_an_assignment_not_another_task_ledger(core):
    service, task_id = core
    service.observe_actor("claude-peer", "claude-session", "claude-code")
    prepared = prepare(core, actor="claude-peer", execution="cross-provider")
    identifier = prepared["assignment"]["id"]
    service.call(
        Context("claude-peer", "claude-session", "start"),
        "assignment_start",
        {"key": "start", "task_id": task_id, "assignment_id": identifier},
    )
    report = service.call(
        Context("claude-peer", "claude-session", "report"),
        "assignment_report",
        {
            "key": "report",
            "task_id": task_id,
            "assignment_id": identifier,
            "verdict": "pass",
            "subject": "rev2",
            "body": "Bounded changed output",
        },
    )
    assert report["assignment"]["result_subject"] == "rev2"
    assert len(service.call(Context("root", "session", "list"), "task_list", {})["tasks"]) == 1


def test_only_one_executor_can_control_a_task(core):
    service, _ = core
    prepare(core, role="executor")
    service.observe_actor("other-child", "session", "codex", parent="root")
    with pytest.raises(CoreError, match="executor-conflict"):
        prepare(core, role="executor", actor="other-child")


def test_executor_can_advance_skill_but_not_finalize_user_task(core):
    service, task_id = core
    identifier = prepare(core, role="executor")["assignment"]["id"]
    call(
        core,
        "assignment_start",
        {"task_id": task_id, "assignment_id": identifier},
        actor="child",
        key="child-start",
    )
    value = service.call(Context("child", "session", "read"), "task_read", {"task_id": task_id})[
        "task"
    ]
    started = call(
        core,
        "task_start",
        {"task_id": task_id, "expected_revision": value["revision"]},
        actor="child",
        key="task-start-child",
    )
    assert started["task"]["state"] == "running"
    with pytest.raises(CoreError, match="stale-owner"):
        call(
            core,
            "task_complete",
            {"task_id": task_id, "expected_revision": started["task"]["revision"], "outcomes": {}},
            actor="child",
            key="cannot-finish",
        )


def test_owner_cannot_impersonate_review_recipient(core):
    _, task_id = core
    identifier = prepare(core, role="reviewer")["assignment"]["id"]
    with pytest.raises(CoreError, match="actor-mismatch"):
        call(
            core,
            "assignment_report",
            {
                "task_id": task_id,
                "assignment_id": identifier,
                "verdict": "pass",
                "body": "Invented review",
                "subject": "rev1",
            },
            key="fake",
        )


def test_session_and_subagent_choices_must_match_observed_execution(core):
    service, _ = core
    service.observe_actor("separate", "other-session", "codex")
    with pytest.raises(CoreError, match="execution-target-mismatch"):
        prepare(core, actor="separate", execution="subagent")
    with pytest.raises(CoreError, match="execution-target-mismatch"):
        prepare(core, actor="child", execution="session")
    assert (
        prepare(core, actor="separate", execution="session")["assignment"]["execution"] == "session"
    )


def test_worker_and_reviewer_roles_cannot_overlap_for_one_actor(core):
    prepare(core, role="worker")
    with pytest.raises(CoreError, match="review-role-conflict"):
        prepare(core, role="reviewer")


def test_owner_can_settle_executor_issued_review_after_executor_returns(core):
    service, task_id = core
    executor = prepare(core, role="executor")["assignment"]["id"]
    call(
        core,
        "assignment_start",
        {"task_id": task_id, "assignment_id": executor},
        actor="child",
        key="start-executor",
    )
    service.observe_actor("reviewer", "session", "codex", parent="child")
    task = service.call(Context("root", "session", "read"), "task_read", {"task_id": task_id})[
        "task"
    ]
    review = call(
        core,
        "assignment_prepare",
        {
            "task_id": task_id,
            "expected_revision": task["revision"],
            "execution": "subagent",
            "reason": "Independent review",
            "scope": "Review the output",
            "recipient": "reviewer",
            "subject": "rev1",
            "role": "reviewer",
            "checkout": str(service.store.root),
        },
        actor="child",
        key="executor-review",
    )["assignment"]["id"]
    report = call(
        core,
        "assignment_report",
        {
            "task_id": task_id,
            "assignment_id": review,
            "verdict": "pass",
            "body": "Reviewed",
            "subject": "rev1",
        },
        actor="reviewer",
        key="review-result",
    )["assignment"]
    call(
        core,
        "assignment_report",
        {
            "task_id": task_id,
            "assignment_id": executor,
            "verdict": "blocked",
            "body": "Returned responsibility",
            "subject": "rev1",
        },
        actor="child",
        key="executor-return",
    )
    accepted = call(
        core,
        "assignment_accept",
        {
            "task_id": task_id,
            "assignment_id": review,
            "source_id": report["result_source"],
            "subject": "rev1",
        },
        key="owner-accept",
    )["assignment"]
    assert accepted["state"] == "accepted"


def test_implementation_context_is_not_reset_by_defining_another_task(core):
    service, task_id = core
    # An earlier native write is retained on its original Task, even if review
    # work is represented by another Task in the same project.
    with service.store.transaction() as tx:
        previous = tx.task(task_id)
        tx.save_task(
            previous.changed(implementation_actors=("child",)), expected_revision=previous.revision
        )
    context = Context("root", "session", "next-task")
    source = service.observe_input(context, "Review the delivered change.", "review-input")
    review_task = call(
        core,
        "task_define",
        {
            "goal": "Independent final review",
            "source_ids": [source.id],
            "acceptance": [{"id": "reviewed"}],
        },
        key="review-task",
    )["task"]
    with pytest.raises(CoreError, match="review-not-independent"):
        prepare((service, review_task["id"]), role="reviewer")


def test_accepted_review_cannot_be_reused_after_reviewed_source_changes(core):
    service, task_id = core
    prepared = prepare(core, role="reviewer")
    assignment_id = prepared["assignment"]["id"]
    report = call(
        core,
        "assignment_report",
        {
            "task_id": task_id,
            "assignment_id": assignment_id,
            "verdict": "pass",
            "body": "Reviewed original bytes",
            "subject": "rev1",
        },
        actor="child",
        key="review-old",
    )
    call(
        core,
        "assignment_accept",
        {
            "task_id": task_id,
            "assignment_id": assignment_id,
            "source_id": report["assignment"]["result_source"],
            "subject": "rev1",
        },
        key="accept-old",
    )
    (service.store.root / "source.py").write_text("changed after review\n")
    with service.store.transaction() as tx:
        with pytest.raises(CoreError, match="evidence-subject-changed"):
            service._outcomes(tx, task_id, {"reviewed": [report["evidence"]["id"]]})


def test_worker_history_cannot_be_relabelled_as_independent_review(core):
    _, task_id = core
    worker = prepare(core, role="worker")["assignment"]
    report = call(
        core,
        "assignment_report",
        {
            "task_id": task_id,
            "assignment_id": worker["id"],
            "verdict": "pass",
            "subject": "rev1",
            "body": "Completed assigned work",
        },
        actor="child",
        key="worked",
    )["assignment"]
    call(
        core,
        "assignment_accept",
        {
            "task_id": task_id,
            "assignment_id": worker["id"],
            "source_id": report["result_source"],
            "subject": "rev1",
        },
        key="accepted-work",
    )
    with pytest.raises(CoreError, match="review-role-conflict"):
        prepare(core, role="reviewer")

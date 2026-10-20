"""태스크 원문·정정·시도·외부 대기와 의존 규칙을 저장소 없이 검증한다."""

from dataclasses import replace

import pytest

from neurath.domain.aggregates.request_source import RequestSource, SourceKind
from neurath.domain.aggregates.task import Task, validate_dependencies
from neurath.domain.errors import ContextNotFound, InvalidTaskState, RevisionConflict
from neurath.domain.task_records import (
    ExternalWait,
    Outcome,
    SubmittedResult,
    TaskDefinition,
    TaskResult,
    TaskStatus,
)


def source(kind=SourceKind.PROMPT, *, corrects_id=None, project_id="project", author=None):
    return RequestSource.create(
        project_id, "session", kind, "original text", author, "ticket:140", corrects_id
    )


def task(*, dependencies=(), session_id="session", requirement=None):
    return Task.create(
        "project",
        session_id,
        source() if requirement is None else requirement,
        "title",
        "required artifact",
        dependencies,
    )


def result(outcome=Outcome.SUCCEEDED):
    return TaskResult(
        outcome=outcome,
        summary="observed outcome",
        observations=("command:run",),
        remaining_work=None if outcome is Outcome.SUCCEEDED else "remaining requirement",
        exit_code=0 if outcome is Outcome.SUCCEEDED else 7,
    )


def correction(work):
    return source(SourceKind.CORRECTION, corrects_id=work.definition.source_id, author="peer")


def wait_condition():
    return ExternalWait(
        target="remote job",
        condition="job completed",
        resume_scope="read result",
        observation="job:running",
    )


@pytest.mark.parametrize("kind", list(SourceKind))
def test_source_kinds_preserve_originals_and_distinguish_requirements(kind):
    original = source(
        kind, corrects_id="prior" if kind is SourceKind.CORRECTION else None, author="peer"
    )
    assert original.body == "original text" and original.session_id == "session"
    assert original.reference == "ticket:140" and original.author == "peer"
    original.require_project("project")
    if kind in (SourceKind.STATUS, SourceKind.SUMMARY):
        with pytest.raises(InvalidTaskState):
            original.require_requirement()
        with pytest.raises(InvalidTaskState):
            task(requirement=original)
    else:
        original.require_requirement()
        assert task(requirement=original).definition.source_id == original.uid


@pytest.mark.parametrize(
    "kind,corrects", [(SourceKind.PROMPT, "id"), (SourceKind.CORRECTION, None)]
)
def test_source_correction_pair_is_required_without_human_authentication(kind, corrects):
    with pytest.raises(InvalidTaskState):
        source(kind, corrects_id=corrects)


def test_source_scope_correction_and_missing_body():
    original = source()
    with pytest.raises(ContextNotFound):
        original.require_project("another")
    with pytest.raises(InvalidTaskState):
        original.require_correction(original.uid)
    fixed = source(SourceKind.CORRECTION, corrects_id=original.uid)
    fixed.require_correction(original.uid)
    with pytest.raises(InvalidTaskState):
        fixed.require_correction("different")
    with pytest.raises(ValueError):
        RequestSource.create("project", "session", SourceKind.PROMPT, " ")


@pytest.mark.parametrize(
    "fields",
    [dict(number=0), dict(title=" "), dict(required_result=""), dict(dependencies=("a", "a"))],
)
def test_invalid_definition_cannot_hide_missing_result(fields):
    values = dict(number=1, source_id="source", title="title", required_result="result")
    values.update(fields)
    with pytest.raises(ValueError):
        TaskDefinition(**values)


@pytest.mark.parametrize("summary,references", [("", ()), ("valid", (" ",))])
def test_submission_requires_actual_candidate_description(summary, references):
    with pytest.raises(ValueError):
        SubmittedResult(summary=summary, references=references)


@pytest.mark.parametrize(
    "fields,error",
    [
        (dict(summary=""), ValueError),
        (dict(observations=()), ValueError),
        (dict(observations=(" ",)), ValueError),
        (dict(remaining_work="left"), InvalidTaskState),
        (dict(exit_code=7), InvalidTaskState),
        (dict(outcome=Outcome.FAILED, remaining_work=None), ValueError),
        (dict(outcome=Outcome.PARTIAL, remaining_work=" "), ValueError),
    ],
)
def test_result_cannot_turn_empty_or_failed_observation_into_success(fields, error):
    values = dict(outcome=Outcome.SUCCEEDED, summary="done", observations=("artifact:path",))
    values.update(fields)
    with pytest.raises(error):
        TaskResult(**values)


@pytest.mark.parametrize(
    "field", ["target", "condition", "resume_scope", "observation", "resolution"]
)
def test_external_wait_requires_target_condition_and_observation(field):
    values = dict(target="job", condition="done", resume_scope="read", observation="running")
    values[field] = " "
    with pytest.raises(ValueError):
        ExternalWait(**values)


def test_task_original_definition_scope_and_revision_are_stable():
    work = task()
    assert work.definition.number == 1 and work.status is TaskStatus.PENDING
    work.require_scope("project", "session")
    work.require_revision(1)
    for project_id, session_id in (("other", "session"), ("project", "other")):
        with pytest.raises(ContextNotFound):
            work.require_scope(project_id, session_id)
    with pytest.raises(RevisionConflict):
        work.require_revision(0)
    with pytest.raises(InvalidTaskState):
        Task(uid="bad", project_id="project", owner_session_id="session", definitions=())
    with pytest.raises(ContextNotFound):
        work.attempt(404)
    with pytest.raises(ContextNotFound):
        task(requirement=source(project_id="other"))


def test_submission_is_not_success_and_failed_attempt_can_retry_with_history():
    work = task()
    work.start((work,))
    with pytest.raises(InvalidTaskState):
        work.start((work,))
    candidate = SubmittedResult(summary="candidate", references=("artifact:draft",))
    work.submit(1, candidate)
    version = work.version
    work.submit(1, candidate)
    assert work.version == version and work.status is TaskStatus.ACTIVE
    work.submit(1, SubmittedResult(summary="revised draft"))
    failed = result(Outcome.FAILED)
    work.report(1, failed, 1)
    assert (
        work.status is TaskStatus.FAILED and work.attempt(1).submission.summary == "revised draft"
    )
    with pytest.raises(InvalidTaskState):
        work.submit(1, candidate)
    with pytest.raises(InvalidTaskState):
        work.report(1, result(), 1)
    version = work.version
    work.report(1, failed, 0)
    assert work.version == version
    work.start((work,))
    assert work.current_attempt_number == 2
    work.report(2, result(), 1)
    assert work.status is TaskStatus.SUCCEEDED and work.attempts[0].result == failed
    assert len(work.attempts) == 2 and work.current_attempt_number == 2
    with pytest.raises(InvalidTaskState):
        work.start((work,))


def test_partial_result_remains_actionable_and_late_old_result_cannot_close_correction():
    work = task()
    work.start((work,))
    work.report(1, result(Outcome.PARTIAL), 1)
    assert work.status is TaskStatus.PENDING and work.attempt(1).result.remaining_work
    work.start((work,))
    original = work.definition
    fixed = correction(work)
    work.correct(fixed, required_result="corrected artifact")
    assert (
        work.definition.title == original.title
        and work.definition.dependencies == original.dependencies
    )
    assert work.definition.number == 2 and work.definitions[0] == original
    work.report(2, result(), 1)
    assert work.status is TaskStatus.PENDING and work.current_attempt_number is None
    assert work.attempt(2).result.outcome is Outcome.SUCCEEDED
    work.start((work,))
    work.report(3, result(), 1)
    assert work.status is TaskStatus.SUCCEEDED


def test_noop_correction_does_not_reopen_success_or_change_metadata():
    work = task()
    work.start((work,))
    work.report(1, result(), 1)
    version = work.version
    work.correct(correction(work))
    assert work.status is TaskStatus.SUCCEEDED and work.version == version
    work.correct(correction(work), title="new title", dependencies=())
    assert work.status is TaskStatus.PENDING and work.definition.title == "new title"
    assert len(work.definitions) == 2


def test_real_wait_preserves_same_attempt_and_independent_work():
    work = task()
    independent = task()
    with pytest.raises(InvalidTaskState):
        work.wait(wait_condition())
    with pytest.raises(InvalidTaskState):
        work.resume("observed")
    work.start((work, independent))
    with pytest.raises(InvalidTaskState):
        work.wait(replace(wait_condition(), resolution="already done"))
    work.wait(wait_condition())
    assert work.status is TaskStatus.WAITING
    assert not work.ready((work, independent)) and independent.ready((work, independent))
    assert work.waits[-1].observation == "job:running"
    with pytest.raises(ValueError):
        work.resume(" ")
    work.resume("job:completed")
    assert work.current_attempt_number == 1 and work.waits[0].resolution == "job:completed"
    assert work.status is TaskStatus.ACTIVE and len(work.attempts) == 1
    work.wait(wait_condition())
    work.report(1, result(), 1)
    assert work.waits[-1].resolution is None


def test_invalidation_preserves_old_results_and_never_counts_as_success():
    work = task()
    work.start((work,))
    fixed = correction(work)
    with pytest.raises(ValueError):
        work.invalidate(fixed, " ")
    work.invalidate(fixed, "actual correction removed this requirement")
    work.report(1, result(), 1)
    assert work.status is TaskStatus.INVALIDATED
    assert work.attempt(1).result.outcome is Outcome.SUCCEEDED
    assert work.invalidated_reason and len(work.definitions) == 2
    with pytest.raises(InvalidTaskState):
        work.start((work,))


def test_dependencies_require_real_success_and_cycle_detection_handles_shared_ancestors():
    root = task()
    left = task(dependencies=(root.uid,))
    right = task(dependencies=(root.uid,))
    leaf = task(dependencies=(left.uid, right.uid))
    graph = (root, left, right, leaf)
    validate_dependencies(graph, leaf.uid, leaf.definition.dependencies)
    assert not leaf.ready(graph) and root.ready(graph)
    with pytest.raises(InvalidTaskState):
        left.start(graph)
    with pytest.raises(InvalidTaskState):
        validate_dependencies(graph, root.uid, (leaf.uid,))
    with pytest.raises(InvalidTaskState):
        validate_dependencies(graph, root.uid, (root.uid,))
    with pytest.raises(InvalidTaskState):
        validate_dependencies(graph, leaf.uid, (root.uid, root.uid))
    with pytest.raises(ContextNotFound):
        validate_dependencies(graph, leaf.uid, ("foreign",))
    root.start(graph)
    root.report(1, result(Outcome.FAILED), 1)
    assert not left.ready(graph)
    root.start(graph)
    root.report(2, result(), 1)
    assert left.ready(graph) and right.ready(graph)
    leaf.correct(correction(leaf), dependencies=(root.uid,))
    assert leaf.ready(graph)


def test_sequence_contracts_accept_lists_without_owning_the_callers_mutable_dependencies():
    prerequisite = task()
    dependencies = [prerequisite.uid]
    work = task(dependencies=dependencies)
    dependencies.clear()
    assert work.definition.dependencies == (prerequisite.uid,)
    validate_dependencies([prerequisite, work], work.uid, [prerequisite.uid])
    assert not work.ready([prerequisite])
    prerequisite.start([prerequisite])
    prerequisite.report(1, result(), 1)
    work.start([prerequisite, work])
    assert work.status is TaskStatus.ACTIVE
    correction_source = correction(work)
    revised_dependencies = []
    work.correct(correction_source, dependencies=revised_dependencies)
    revised_dependencies.append(prerequisite.uid)
    assert work.definition.dependencies == ()
    assert len(work.definitions) == 2 and len(work.attempts) == 1

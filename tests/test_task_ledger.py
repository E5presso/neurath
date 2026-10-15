"""Real temporary SQLite requests: requirements, attempts, readiness and TODO."""

import pytest
from sqlalchemy import select

from neurath.domain.core import ContextNotFound, RevisionConflict
from neurath.domain.tasks import InvalidTaskTransition
from neurath.infrastructure.core_database import CoreDatabase
from neurath.infrastructure.core_schema import task_attempts
from neurath.transport.core_requests import build_core, build_task_ledger


@pytest.fixture
def ledger(tmp_path):
    db = tmp_path / "data" / "core.db"
    CoreDatabase(db).initialize()
    root = tmp_path / "project"
    root.mkdir()
    ctx = build_core(db).open_session(str(root), "test", "session-1")
    api = build_task_ledger(db)
    source = api.record_source(
        ctx.project.id,
        ctx.session.id,
        kind="request",
        text="Implement both login and logout",
        reference="prompt:1",
    )
    return db, ctx, api, source


def create(ledger, title="login"):
    _, ctx, api, source = ledger
    return api.create_task(ctx.project.id, ctx.session.id, title=title, source_id=source.id)


def start(api, task):
    return api.start_task(task.project_id, task.id, expected_revision=task.revision)


def result(api, task, attempt, outcome="succeeded", **kwargs):
    return api.report_result(
        task.project_id,
        task.id,
        attempt_id=attempt.id,
        outcome=outcome,
        summary="Observed host output",
        references=("file:actual-result",),
        **kwargs,
    )


def correction(ledger, task, cancel=False):
    _, ctx, api, source = ledger
    update = api.record_source(
        ctx.project.id,
        ctx.session.id,
        kind="correction",
        text="Use email for login",
        reference="prompt:2",
        parent_id=source.id,
        author="delegated-agent",
    )
    return api.revise_task(
        ctx.project.id,
        task.id,
        expected_revision=task.revision,
        source_id=update.id,
        title="email login",
        reason="User correction",
        cancel=cancel,
    )


def test_original_sources_and_agent_handoff_are_reused_without_new_human_input(ledger):
    db, ctx, api, source = ledger
    other = build_core(db).open_session(ctx.session.working_directory, "other-provider", "delegate")
    task = api.create_task(ctx.project.id, other.session.id, title="logout", source_id=source.id)
    fresh = build_task_ledger(db)
    assert fresh.get_source(ctx.project.id, task.source_id) == source
    assert fresh.list_tasks(ctx.project.id, ctx.session.id).tasks == ()
    assert fresh.list_tasks(ctx.project.id, other.session.id).tasks == (task,)


@pytest.mark.parametrize("kind", ["question", "context"])
def test_status_questions_and_old_summaries_are_not_new_work(ledger, kind):
    _, ctx, api, _ = ledger
    task = create(ledger)
    source = api.record_source(
        ctx.project.id, ctx.session.id, kind=kind, text="What remains?", reference="chat:3"
    )
    with pytest.raises(InvalidTaskTransition):
        api.create_task(ctx.project.id, ctx.session.id, title="new goal", source_id=source.id)
    with pytest.raises(InvalidTaskTransition):
        api.revise_task(
            ctx.project.id,
            task.id,
            expected_revision=1,
            source_id=source.id,
            title="old goal",
            reason="summary",
        )
    assert api.list_tasks(ctx.project.id, ctx.session.id).tasks == (task,)


def test_correction_is_targeted_history_preserved_and_old_result_cannot_close_it(ledger):
    _, ctx, api, source = ledger
    sibling = create(ledger, "logout")
    task, attempt = start(api, create(ledger))
    revised = correction(ledger, task)
    unchanged, late = result(api, revised, attempt)
    assert unchanged == revised
    assert not late.applied
    assert api.get_task(ctx.project.id, sibling.id) == sibling
    history = api.history(ctx.project.id, revised.id)
    assert history["definitions"][0]["source_id"] == source.id
    assert len(history["definitions"]) == 2
    assert history["results"] == (late,)
    resumed, new_attempt = start(api, revised)
    finished, _ = result(api, resumed, new_attempt)
    assert finished.status == "succeeded"


def test_submission_is_not_success_and_todo_comes_from_same_ledger(ledger):
    db, ctx, api, _ = ledger
    task, attempt = start(api, create(ledger))
    submitted, report = result(api, task, attempt, "submitted")
    assert submitted.status == "active"
    assert report.applied
    fresh = build_task_ledger(db)
    before = fresh.list_tasks(ctx.project.id, ctx.session.id)
    assert before.todo[0]["status"] == "active"
    assert not before.all_terminal
    done, _ = result(fresh, submitted, attempt)
    after = api.list_tasks(ctx.project.id, ctx.session.id)
    assert after.tasks == (done,)
    assert after.todo[0]["text"] == "[succeeded] login"
    assert after.all_successful
    assert after.all_terminal
    # Consumer mutation/display failure cannot change persisted task state.
    after.todo[0]["status"] = "failed"
    assert api.get_task(ctx.project.id, task.id) == done


@pytest.mark.parametrize("outcome", ["failed", "partial"])
def test_failure_retains_obligation_and_retry_attempt_history(ledger, outcome):
    db, ctx, api, _ = ledger
    task, attempt = start(api, create(ledger))
    failed, observation = result(
        api, task, attempt, outcome, remaining="logout still unimplemented"
    )
    listing = api.list_tasks(ctx.project.id, ctx.session.id)
    assert listing.all_terminal and not listing.all_successful
    assert failed.reason == "logout still unimplemented"
    assert failed.id in listing.ready_ids
    retry, next_attempt = start(api, failed)
    assert next_attempt.id != attempt.id
    complete, _ = result(api, retry, next_attempt)
    assert complete.status == "succeeded"
    assert observation in api.history(ctx.project.id, task.id)["results"]
    with CoreDatabase(db).transaction() as work:
        assert len(work.connection.execute(select(task_attempts)).all()) == 2


def test_external_wait_is_specific_and_independent_work_stays_ready(ledger):
    _, ctx, api, _ = ledger
    task = create(ledger)
    independent = create(ledger, "logout")
    with pytest.raises(ValueError):
        api.wait_for_external(
            ctx.project.id,
            task.id,
            expected_revision=1,
            target="user",
            evidence="",
            resolution_condition="answer",
        )
    waiting, wait_id = api.wait_for_external(
        ctx.project.id,
        task.id,
        expected_revision=1,
        target="CI run 12",
        evidence="ci:12:in-progress",
        resolution_condition="CI completes",
    )
    listing = api.list_tasks(ctx.project.id, ctx.session.id)
    assert listing.ready_ids == (independent.id,)
    with pytest.raises(InvalidTaskTransition):
        start(api, waiting)
    ready = api.resolve_external(
        ctx.project.id,
        task.id,
        expected_revision=waiting.revision,
        wait_id=wait_id,
        observation="ci:12:complete",
    )
    assert set(api.list_tasks(ctx.project.id, ctx.session.id).ready_ids) == {
        task.id,
        independent.id,
    }
    assert ready.status == "pending"


def test_wait_during_active_attempt_resumes_same_attempt(ledger):
    db, ctx, api, _ = ledger
    task, attempt = start(api, create(ledger))
    waiting, wait_id = api.wait_for_external(
        ctx.project.id,
        task.id,
        expected_revision=task.revision,
        target="job",
        evidence="job:running",
        resolution_condition="job result available",
    )
    with pytest.raises(InvalidTaskTransition):
        result(api, waiting, attempt)
    assert api.history(ctx.project.id, task.id)["results"] == ()
    ready = api.resolve_external(
        ctx.project.id,
        task.id,
        expected_revision=waiting.revision,
        wait_id=wait_id,
        observation="job:done",
    )
    resumed, same_attempt = start(api, ready)
    assert same_attempt.id == attempt.id
    result(api, resumed, same_attempt)
    with CoreDatabase(db).transaction() as work:
        assert len(work.connection.execute(select(task_attempts)).all()) == 1


def test_task_dependencies_cycles_and_failed_dependency(ledger):
    _, ctx, api, _ = ledger
    prerequisite = create(ledger)
    dependent = create(ledger, "integration")
    dependent = api.add_dependency(
        ctx.project.id, dependent.id, expected_revision=1, depends_on=prerequisite.id
    )
    with pytest.raises(InvalidTaskTransition):
        api.add_dependency(
            ctx.project.id, prerequisite.id, expected_revision=1, depends_on=dependent.id
        )
    with pytest.raises(InvalidTaskTransition):
        start(api, dependent)
    running, attempt = start(api, prerequisite)
    failed, _ = result(api, running, attempt, "failed", remaining="fix error")
    assert dependent.id not in api.list_tasks(ctx.project.id, ctx.session.id).ready_ids
    running, attempt = start(api, failed)
    result(api, running, attempt)
    assert dependent.id in api.list_tasks(ctx.project.id, ctx.session.id).ready_ids


def test_no_unobserved_success_partial_success_or_duplicate_final_result(ledger):
    _, ctx, api, _ = ledger
    task, attempt = start(api, create(ledger))
    with pytest.raises(ValueError):
        api.report_result(
            ctx.project.id, task.id, attempt_id=attempt.id, outcome="succeeded", summary="Done"
        )
    with pytest.raises(InvalidTaskTransition):
        result(api, task, attempt, remaining="unfinished")
    result(api, task, attempt)
    with pytest.raises(InvalidTaskTransition):
        result(api, task, attempt)
    assert len(api.history(ctx.project.id, task.id)["results"]) == 1


def test_stale_update_does_not_erase_progress_and_cancel_retains_late_results(ledger):
    _, ctx, api, _ = ledger
    original = create(ledger)
    task, attempt = start(api, original)
    with pytest.raises(RevisionConflict):
        start(api, original)
    cancelled = correction(ledger, task, cancel=True)
    preserved, late = result(api, cancelled, attempt)
    assert preserved.status == "invalidated" and not late.applied
    listing = api.list_tasks(ctx.project.id, ctx.session.id)
    assert listing.all_terminal and not listing.all_successful
    assert not listing.ready_ids


def test_cross_project_source_and_attempt_references_rejected(ledger, tmp_path):
    db, ctx, api, source = ledger
    directory = tmp_path / "other"
    directory.mkdir()
    other = build_core(db).open_session(str(directory), "test", "session-1")
    with pytest.raises(ContextNotFound):
        api.create_task(other.project.id, other.session.id, title="leak", source_id=source.id)
    one, attempt = start(api, create(ledger))
    two, _ = start(api, create(ledger, "logout"))
    with pytest.raises(ContextNotFound):
        result(api, two, attempt)
    assert api.get_task(ctx.project.id, one.id) == one


def test_upgrade_keeps_existing_identity_and_revision(tmp_path):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine

    path = tmp_path / "old-core.db"
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as connection:
        config = Config()
        config.set_main_option("script_location", "neurath.infrastructure:core_migrations")
        config.attributes["connection"] = connection
        command.upgrade(config, "core_0001")
        connection.exec_driver_sql("INSERT INTO core_projects VALUES ('old-project','/old')")
    engine.dispose()
    CoreDatabase(path).initialize()
    with CoreDatabase(path).transaction() as work:
        assert work.identities.get_project("old-project").root_path == "/old"

    from sqlalchemy import inspect

    fresh_path = tmp_path / "fresh.db"
    CoreDatabase(fresh_path).initialize()

    def shape(db_path):
        with CoreDatabase(db_path).transaction() as work:
            inspector = inspect(work.connection)
            return {
                name: (
                    [c["name"] for c in inspector.get_columns(name)],
                    inspector.get_foreign_keys(name),
                    inspector.get_check_constraints(name),
                )
                for name in inspector.get_table_names()
            }

    assert shape(path) == shape(fresh_path)


def test_observed_command_and_artifact_are_persisted_after_process_exit(ledger, tmp_path):
    import subprocess
    import sys

    db, ctx, api, _ = ledger
    task, attempt = start(api, create(ledger))
    artifact = tmp_path / "result.txt"
    command = subprocess.run(
        [sys.executable, "-c", "print('verified result')"],
        capture_output=True,
        text=True,
        check=True,
    )
    artifact.write_text(command.stdout)
    done, recorded = api.report_result(
        ctx.project.id,
        task.id,
        attempt_id=attempt.id,
        outcome="succeeded",
        summary=command.stdout.strip(),
        references=(artifact.as_uri(),),
    )
    assert done.status == "succeeded"
    assert build_task_ledger(db).history(ctx.project.id, task.id)["results"] == (recorded,)
    assert artifact.read_text().strip() == recorded.summary


def test_result_arriving_after_wait_resolution_needs_no_resubmission(ledger):
    _, ctx, api, _ = ledger
    task, attempt = start(api, create(ledger))
    waiting, wait_id = api.wait_for_external(
        ctx.project.id,
        task.id,
        expected_revision=task.revision,
        target="job",
        evidence="job:running",
        resolution_condition="job finished",
    )
    ready = api.resolve_external(
        ctx.project.id,
        task.id,
        expected_revision=waiting.revision,
        wait_id=wait_id,
        observation="job:finished",
    )
    done, observation = result(api, ready, attempt)
    assert observation.applied
    assert done.status == "succeeded"

"""Persisted workflow behavior and real, bounded subprocess execution."""

from dataclasses import replace
import json
import sys
import threading

import pytest

from neurath.domain.core import ContextNotFound, RevisionConflict
from neurath.domain.tasks import InvalidTaskTransition
from neurath.domain.workflows import Definition, InvalidWorkflow, Observation, Phase
from neurath.infrastructure.core_database import CoreDatabase
from neurath.transport.core_requests import build_core, build_task_ledger, build_workflow_runner
from neurath.transport.workflow_host import CommandHost


@pytest.fixture
def world(tmp_path):
    db = tmp_path / "core.db"
    CoreDatabase(db).initialize()
    ctx = build_core(db).open_session(str(tmp_path), "test", "workflow")
    ledger = build_task_ledger(db)
    source = ledger.record_source(
        ctx.project.id,
        ctx.session.id,
        kind="request",
        text="Build and verify",
        reference="prompt:1",
    )
    task = ledger.create_task(ctx.project.id, ctx.session.id, title="Build", source_id=source.id)
    return db, ctx, ledger, task, build_workflow_runner(db)


def phase(name="build", **kwargs):
    return Phase(name, (sys.executable, "-c", "print('actual execution')"), name, "rev-1", **kwargs)


def definition(*phases):
    return Definition("selected-skill", "1", "Build and verify", phases or (phase(),))


def start(world, spec=None, inputs=None):
    _, ctx, _, task, runner = world
    return runner.start(
        ctx.project.id,
        task.id,
        definition=spec or definition(),
        inputs=inputs or {},
        expected_task_revision=task.revision,
    )


def success(execution, **kwargs):
    return Observation(
        "observed",
        "succeeded",
        "Actual result",
        execution.phase.target,
        execution.phase.target_revision,
        ("artifact:observed",),
        satisfied=("execution",),
        **kwargs,
    )


class Host:
    deduplicates = False

    def __init__(self, execute=None):
        self.executions = []
        self.notifications = []
        self.found = None
        self.action = execute or success
        self.lookups = []

    def execute(self, execution):
        self.executions.append(execution)
        return self.action(execution)

    def lookup(self, execution):
        self.lookups.append(execution.id)
        return self.found

    def notify(self, execution, message):
        self.notifications.append((execution.id, message))


def dispatch(world, run, host=None):
    return world[4].dispatch(
        run.project_id,
        run.id,
        phase_id=run.current.id,
        expected_revision=run.revision,
        host=host or Host(),
    )[0]


def revise(world, run, spec, **kwargs):
    return world[4].revise(
        run.project_id,
        run.id,
        expected_revision=run.revision,
        definition=spec,
        inputs=run.inputs,
        reason="Adapt based on evidence",
        **kwargs,
    )


def test_reads_do_not_execute_and_real_process_finishes_procedure_not_task(world, tmp_path):
    db, ctx, ledger, task, runner = world
    run = start(world)
    assert build_workflow_runner(db).current(ctx.project.id, run.id) == run
    assert not runner.history(ctx.project.id, run.id)["attempts"]
    completed = dispatch(world, run, CommandHost(tmp_path))
    assert completed.status == "completed"
    assert ledger.get_task(ctx.project.id, task.id).status == "pending"
    history = runner.history(ctx.project.id, run.id)
    assert len(history["results"]) == 1
    result = json.loads(history["results"][0]["payload"])
    assert "actual execution" in result["output"]
    assert result["references"][0].startswith("process:")
    assert build_workflow_runner(db).current(ctx.project.id, run.id).status == "completed"


def test_required_phases_block_task_success_and_duplicate_finalize_is_idempotent(world):
    _, ctx, ledger, task, runner = world
    run = start(world, definition(phase(), phase("review", reviewer="independent")))
    task = ledger.get_task(ctx.project.id, task.id)
    task, attempt = ledger.start_task(ctx.project.id, task.id, expected_revision=task.revision)
    with pytest.raises(InvalidTaskTransition):
        ledger.report_result(
            ctx.project.id,
            task.id,
            attempt_id=attempt.id,
            outcome="succeeded",
            summary="claim",
            references=("artifact",),
        )
    with pytest.raises(InvalidWorkflow):
        runner.skip(
            ctx.project.id,
            run.id,
            phase_id="build",
            expected_revision=run.revision,
            reason="too slow",
        )
    run = dispatch(world, run)
    wrong = Host()
    run = dispatch(world, run, wrong)
    assert run.states["review"]["status"] == "failed"
    reviewer = Host(lambda e: success(e, reviewer="independent"))
    run = dispatch(world, run, reviewer)
    assert run.status == "completed"
    before = runner.history(ctx.project.id, run.id)
    same, applied = runner.report_result(
        ctx.project.id,
        run.id,
        attempt_id=reviewer.executions[0].id,
        observation=success(reviewer.executions[0], reviewer="independent"),
    )
    assert same == run and applied
    assert runner.history(ctx.project.id, run.id) == before
    done, _ = ledger.report_result(
        ctx.project.id,
        task.id,
        attempt_id=attempt.id,
        outcome="succeeded",
        summary="All goal criteria observed",
        references=("artifact",),
    )
    assert done.status == "succeeded"


def test_failed_process_retries_same_phase_and_late_success_cannot_complete_new_attempt(
    world, tmp_path
):
    _, ctx, _, _, runner = world
    bad = replace(phase(), action=(sys.executable, "-c", "raise SystemExit(7)"))
    run = start(world, definition(bad, phase("check")))
    run = dispatch(world, run, CommandHost(tmp_path))
    old = runner.history(ctx.project.id, run.id)["attempts"][0]["id"]
    assert run.current.id == "build" and run.states["build"]["status"] == "failed"
    run = revise(world, run, definition(phase(), phase("check")))
    pending_host = Host(lambda e: runner.unknown(e, "running elsewhere"))
    run = dispatch(world, run, pending_host)
    current = run.states["build"]["attempt_id"]
    observed = Observation(
        "late", "succeeded", "late old success", "build", "rev-1", ("job:old",), ("execution",)
    )
    unchanged, applied = runner.report_result(
        ctx.project.id, run.id, attempt_id=old, observation=observed
    )
    assert not applied and unchanged.states["build"]["attempt_id"] == current
    assert unchanged.current.id == "build"
    pending_host.found = success(pending_host.executions[0])
    run, applied = runner.reconcile(ctx.project.id, run.id, attempt_id=current, host=pending_host)
    assert applied and run.current.id == "check"


def test_lost_mutation_restart_queries_without_replay_and_notifies(world):
    db, ctx, ledger, task, runner = world
    run = start(world, definition(phase(mutation=True)))

    def mutate_and_lose(execution):
        # A new write connection succeeds while host work is running: no held DB lock.
        ledger.record_source(
            ctx.project.id,
            ctx.session.id,
            kind="context",
            text="external mutation happened",
            reference="external:receipt",
        )
        raise ConnectionError("response lost")

    host = Host(mutate_and_lose)
    run = dispatch(world, run, host)
    assert len(host.executions) == 1 and host.notifications
    attempt = host.executions[0]
    fresh = build_workflow_runner(db)
    run, _ = fresh.reconcile(ctx.project.id, run.id, attempt_id=attempt.id, host=host)
    assert len(host.executions) == 1 and host.lookups == [attempt.id]
    assert run.states["build"]["status"] == "waiting"
    with pytest.raises(InvalidWorkflow):
        dispatch(world, run, host)
    # Independent work remains usable while this exact external result is unknown.
    sibling = ledger.create_task(
        ctx.project.id, ctx.session.id, title="Independent", source_id=task.source_id
    )
    ledger.start_task(ctx.project.id, sibling.id, expected_revision=sibling.revision)
    host.found = success(attempt)
    run, applied = fresh.reconcile(ctx.project.id, run.id, attempt_id=attempt.id, host=host)
    assert applied and run.status == "completed" and len(host.executions) == 1


def test_guaranteed_dedup_reuses_external_key_after_lookup(world):
    _, ctx, _, _, runner = world
    host = Host(lambda e: runner.unknown(e, "lost"))
    run = dispatch(world, start(world, definition(phase(mutation=True))), host)
    host.deduplicates = True
    host.action = success
    run, _ = runner.reconcile(ctx.project.id, run.id, attempt_id=host.executions[0].id, host=host)
    assert run.status == "completed"
    assert host.executions[0].id == host.executions[1].id == host.lookups[0]


def test_conditional_branch_and_optional_skip_keep_reason(world):
    _, ctx, _, _, runner = world
    run = start(
        world, definition(phase(when="needed"), phase("extra", required=False)), {"needed": False}
    )
    with pytest.raises(InvalidWorkflow):
        dispatch(world, run)
    run = runner.skip(
        ctx.project.id,
        run.id,
        phase_id="build",
        expected_revision=run.revision,
        reason="Definition input needed=false",
    )
    run = runner.skip(
        ctx.project.id,
        run.id,
        phase_id="extra",
        expected_revision=run.revision,
        reason="Optional report not useful",
    )
    assert run.status == "completed" and run.states["build"]["reason"]


def test_changed_target_invalidates_only_related_evidence_and_keeps_history(world):
    _, ctx, _, _, runner = world
    spec = definition(phase(), phase("docs"), phase("review", depends_on=("build",)))
    run = start(world, spec)
    for _ in range(3):
        run = dispatch(world, run)
    changed = replace(
        spec,
        version="2",
        phases=(replace(spec.phases[0], target_revision="rev-2"), *spec.phases[1:]),
    )
    run = revise(world, run, changed)
    assert run.states["build"]["status"] == run.states["review"]["status"] == "pending"
    assert run.states["docs"]["status"] == "succeeded"
    assert len(runner.history(ctx.project.id, run.id)["results"]) == 3
    run = dispatch(world, run)
    assert run.current.id == "review"
    run = dispatch(world, run)
    assert run.status == "completed"
    assert len(runner.history(ctx.project.id, run.id)["attempts"]) == 5


def test_scope_correction_preserves_unaffected_waiting_attempt_and_observed_result(world):
    _, ctx, ledger, task, runner = world
    spec = definition(phase(mutation=True), phase("docs"))
    host = Host(lambda e: runner.unknown(e, "result not received"))
    run = dispatch(world, start(world, spec), host)
    attempt = host.executions[0]
    correction = ledger.record_source(
        ctx.project.id,
        ctx.session.id,
        kind="correction",
        text="Only change documentation format",
        reference="prompt:2",
        parent_id=task.source_id,
    )
    task = ledger.get_task(ctx.project.id, task.id)
    ledger.revise_task(
        ctx.project.id,
        task.id,
        expected_revision=task.revision,
        source_id=correction.id,
        title="Build, different docs",
        reason="Requested docs correction",
    )
    host.found = success(attempt)
    run, applied = runner.reconcile(ctx.project.id, run.id, attempt_id=attempt.id, host=host)
    assert not applied  # unresolved applicability is retained until correction reconciliation
    revised = replace(
        spec, version="2", phases=(spec.phases[0], replace(spec.phases[1], target_revision="rev-2"))
    )
    run = revise(world, run, revised, correction_source_id=correction.id)
    run, applied = runner.reconcile(ctx.project.id, run.id, attempt_id=attempt.id, host=host)
    assert applied and run.current.id == "docs" and len(host.executions) == 1
    assert len(runner.history(ctx.project.id, run.id)["results"]) == 2


@pytest.mark.parametrize("change", ["goal", "required", "condition", "reviewer"])
def test_method_edit_cannot_erase_required_scope(world, change):
    spec = definition(phase(reviewer="independent"))
    run = start(world, spec)
    changed = {
        "goal": replace(spec, purpose="Different goal"),
        "required": replace(spec, phases=(replace(spec.phases[0], required=False),)),
        "condition": replace(spec, phases=(replace(spec.phases[0], conditions=("weaker",)),)),
        "reviewer": replace(spec, phases=(replace(spec.phases[0], reviewer=""),)),
    }[change]
    with pytest.raises(InvalidWorkflow):
        revise(world, run, changed)


def test_finite_review_loop_stops_unresolved_and_preserves_defects_and_changes(world):
    _, ctx, _, _, runner = world
    run = start(world, definition(phase(max_attempts=5, no_progress_limit=2)))
    host = Host(
        lambda e: replace(
            success(e), outcome="failed", defects=("missing case",), changes="attempted fix"
        )
    )
    run = dispatch(world, run, host)
    run = dispatch(world, run, host)
    with pytest.raises(InvalidWorkflow):
        dispatch(world, run, host)
    assert run.status != "completed" and run.current.id == "build"
    history = runner.history(ctx.project.id, run.id)
    assert len(history["attempts"]) == 2
    assert all(json.loads(r["payload"])["changes"] == "attempted fix" for r in history["results"])
    # A method edit cannot silently replenish the finite review budget.
    run = revise(world, run, replace(run.definition, version="2"))
    with pytest.raises(InvalidWorkflow):
        dispatch(world, run, host)


@pytest.mark.parametrize("mode", ["timeout", "interrupt", "large"])
def test_actual_timeout_interrupt_and_large_output_are_bounded(world, tmp_path, mode):
    _, ctx, _, _, runner = world
    cancel = threading.Event()
    if mode == "interrupt":
        cancel.set()
    code = "print('x'*200000)" if mode == "large" else "import time; time.sleep(30)"
    spec = definition(
        replace(phase(timeout=0.1, output_limit=512), action=(sys.executable, "-c", code))
    )
    run = dispatch(world, start(world, spec), CommandHost(tmp_path, cancelled=cancel))
    result = json.loads(runner.history(ctx.project.id, run.id)["results"][0]["payload"])
    expected = {"timeout": "timed_out", "interrupt": "interrupted", "large": "succeeded"}[mode]
    assert result["outcome"] == expected and len(result["output"]) <= 512
    if mode == "large":
        assert "truncated" in result["summary"]
    else:
        assert run.current.id == "build" and run.states["build"]["status"] == "failed"


def test_yield_resume_stale_write_project_boundary_and_notification_failure(world, tmp_path):
    db, ctx, _, _, runner = world
    run = start(world)
    paused = runner.yield_run(
        ctx.project.id, run.id, expected_revision=run.revision, reason="Host budget exhausted"
    )
    assert paused.reason == "Host budget exhausted"
    with pytest.raises(InvalidWorkflow):
        dispatch(world, paused)
    with pytest.raises(RevisionConflict):
        runner.resume(ctx.project.id, run.id, expected_revision=run.revision)
    resumed = build_workflow_runner(db).resume(
        ctx.project.id, run.id, expected_revision=paused.revision
    )
    other_dir = tmp_path / "other"
    other_dir.mkdir()
    other = build_core(db).open_session(str(other_dir), "test", "other")
    with pytest.raises(ContextNotFound):
        runner.current(other.project.id, run.id)
    host = Host(lambda e: runner.unknown(e, "unknown execution"))
    host.notify = lambda e, m: (_ for _ in ()).throw(RuntimeError("notification delivery failed"))
    with pytest.raises(RuntimeError, match="notification delivery"):
        dispatch(world, resumed, host)
    persisted = runner.current(ctx.project.id, run.id)
    assert persisted.states["build"]["status"] == "waiting"


def test_unknown_mutation_cannot_be_hidden_by_revision(world):
    run = dispatch(
        world,
        start(world, definition(phase(mutation=True))),
        Host(lambda e: world[4].unknown(e, "unknown")),
    )
    changed = definition(replace(run.definition.phases[0], target_revision="rev-2"))
    with pytest.raises(InvalidWorkflow, match="Reconcile outstanding"):
        revise(world, run, changed)


def test_upgrade_0002_preserves_sources_tasks_and_matches_fresh_metadata(tmp_path):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect
    from neurath.infrastructure.core_schema import metadata

    path = tmp_path / "previous.db"
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as connection:
        config = Config()
        config.set_main_option("script_location", "neurath.infrastructure:core_migrations")
        config.attributes["connection"] = connection
        command.upgrade(config, "core_0002")
        connection.exec_driver_sql("INSERT INTO core_projects VALUES ('project','/fixture')")
        connection.exec_driver_sql(
            "INSERT INTO core_sessions VALUES ('session','project','test','host','/fixture',1)"
        )
        connection.exec_driver_sql(
            "INSERT INTO core_sources VALUES ('source','project','session','request',"
            "'Original request','prompt:original','','' || NULL)"
        )
        connection.exec_driver_sql(
            "INSERT INTO core_tasks VALUES ('task','project','session','Unfinished',"
            "'source','pending',1,1,'')"
        )
    engine.dispose()
    CoreDatabase(path).initialize()
    assert build_task_ledger(path).get_source("project", "source").text == "Original request"
    assert build_task_ledger(path).get_task("project", "task").status == "pending"

    fresh = tmp_path / "fresh.db"
    CoreDatabase(fresh).initialize()
    model = create_engine("sqlite://")
    metadata.create_all(model)

    def shape(connection):
        inspector = inspect(connection)
        return {
            name: (
                [dict(c) for c in inspector.get_columns(name)],
                inspector.get_foreign_keys(name),
                inspector.get_unique_constraints(name),
            )
            for name in inspector.get_table_names()
            if name != "core_schema_revision"
        }

    # SQLAlchemy type instances compare by representation, not object identity.
    with CoreDatabase(path).transaction() as upgraded, CoreDatabase(fresh).transaction() as created:
        assert str(shape(upgraded.connection)) == str(shape(created.connection))
        with model.connect() as connection:
            assert str(shape(upgraded.connection)) == str(shape(connection))
    model.dispose()


def test_review_max_rounds_even_with_progress_and_obsolete_target_is_not_success(world):
    _, ctx, _, _, runner = world
    run = start(world, definition(phase(max_attempts=2, no_progress_limit=5)))
    host = Host(lambda e: replace(success(e), outcome="failed", defects=(e.id,)))
    run = dispatch(world, run, host)
    run = dispatch(world, run, host)
    with pytest.raises(InvalidWorkflow):
        dispatch(world, run, host)
    assert len(runner.history(ctx.project.id, run.id)["attempts"]) == 2


def test_stale_target_observation_and_duplicate_conflict_do_not_advance(world):
    _, ctx, _, _, runner = world
    host = Host(lambda e: replace(success(e), target_revision="old-revision"))
    run = dispatch(world, start(world), host)
    assert run.current.id == "build"
    assert not runner.history(ctx.project.id, run.id)["results"][0]["applied"]
    with pytest.raises(InvalidWorkflow, match="different observation"):
        runner.report_result(
            ctx.project.id,
            run.id,
            attempt_id=host.executions[0].id,
            observation=success(host.executions[0]),
        )

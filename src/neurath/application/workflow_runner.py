"""Request-scoped workflow use cases. Host calls never hold database transactions."""

import json
from dataclasses import asdict, replace
from typing import Protocol
from uuid import uuid4

from neurath.domain.core import RevisionConflict
from neurath.domain.workflows import Execution, InvalidWorkflow, Observation, Run


class ExecutionHost(Protocol):
    """Adapters obtain real execution/reviewer observations under native host permissions.

    execute must use execution.id as the external idempotency key when claiming
    deduplicates=True. lookup returns an observed result or None, never an invented
    failure. notify must actually deliver the unresolved-state notice (or raise).
    """

    deduplicates: bool

    def execute(self, execution: Execution) -> Observation: ...
    def lookup(self, execution: Execution) -> Observation | None: ...
    def notify(self, execution: Execution, message: str) -> None: ...


class WorkflowRunner:
    def __init__(self, database):
        self.database = database

    def start(self, project_id, task_id, *, definition, inputs, expected_task_revision):
        definition.validate(inputs)
        with self.database.transaction(write=True) as work:
            task = work.tasks.get(project_id, task_id)
            if task.revision != expected_task_revision:
                raise RevisionConflict("Task changed; read current task")
            task.require("pending", "active", "failed")
            if any(r.status != "completed" for r in work.workflows.for_task(task_id)):
                raise InvalidWorkflow("Resume the existing unfinished run")
            run = Run(
                uuid4().hex,
                project_id,
                task_id,
                1,
                definition,
                dict(inputs),
                task.definition_revision,
            )
            run.initialize()
            work.workflows.create(run)
            # Selected procedures remain part of the same unfinished task.
            work.tasks.change(task, task.revision, reason="Selected procedure is unfinished")
            return run

    def current(self, project_id, run_id):
        with self.database.transaction() as work:
            return work.workflows.get(project_id, run_id)

    def history(self, project_id, run_id):
        with self.database.transaction() as work:
            work.workflows.get(project_id, run_id)
            return work.workflows.history(run_id)

    @staticmethod
    def checked(work, project_id, run_id, expected_revision):
        run = work.workflows.get(project_id, run_id)
        if run.revision != expected_revision:
            raise RevisionConflict("Workflow changed; read current state")
        task = work.tasks.get(project_id, run.task_id)
        if task.definition_revision != run.task_definition_revision or task.status == "invalidated":
            raise InvalidWorkflow("Reconcile the workflow with the current task correction")
        return run

    def skip(self, project_id, run_id, *, phase_id, expected_revision, reason):
        with self.database.transaction(write=True) as work:
            run = self.checked(work, project_id, run_id, expected_revision)
            run.skip(phase_id, reason)
            work.workflows.save(run)
            return run

    def dispatch(self, project_id, run_id, *, phase_id, expected_revision, host):
        with self.database.transaction(write=True) as work:
            run = self.checked(work, project_id, run_id, expected_revision)
            execution = run.begin(phase_id, uuid4().hex)
            work.workflows.add_attempt(execution)
            work.workflows.save(run)
        # A crash after commit is recoverable through reconcile, not a blind new attempt.
        try:
            observation = host.execute(execution)
        except Exception as error:
            observation = self.unknown(
                execution, f"Execution response unavailable: {type(error).__name__}"
            )
        result = self.report_result(
            project_id, run_id, attempt_id=execution.id, observation=observation
        )
        if observation.outcome == "waiting":
            host.notify(execution, observation.summary)
        return result

    @staticmethod
    def unknown(execution, reason):
        return Observation(
            "unknown",
            "waiting",
            reason,
            execution.phase.target,
            execution.phase.target_revision,
            (f"attempt:{execution.id}",),
        )

    def reconcile(self, project_id, run_id, *, attempt_id, host):
        with self.database.transaction() as work:
            run = work.workflows.get(project_id, run_id)
            execution = work.workflows.attempt(run_id, attempt_id)
            state = run.states.get(execution.phase.id)
            if (
                not state
                or state["attempt_id"] != attempt_id
                or state["status"] not in {"running", "waiting"}
            ):
                raise InvalidWorkflow("Only an outstanding current attempt can be reconciled")
        # Lookup is always tried before a deduplicated retry; absent capability never
        # authorizes replay, even for reads (host may have misclassified a mutation).
        try:
            observation = host.lookup(execution)
        except Exception:
            observation = None
        if observation is None and host.deduplicates:
            try:
                observation = host.execute(execution)
            except Exception:
                observation = None
        if observation is None:
            observation = self.unknown(
                execution, "External result unknown; automatic replay withheld"
            )
        result = self.report_result(
            project_id, run_id, attempt_id=attempt_id, observation=observation
        )
        if observation.outcome == "waiting":
            host.notify(execution, observation.summary)
        return result

    def report_result(self, project_id, run_id, *, attempt_id, observation):
        observation.validate()
        with self.database.transaction(write=True) as work:
            run = work.workflows.get(project_id, run_id)
            execution = work.workflows.attempt(run_id, attempt_id)
            # Bound persisted output even for third-party host adapters.
            observation = replace(
                observation, output=observation.output[: execution.phase.output_limit]
            )
            previous = work.workflows.result(attempt_id, observation.key)
            if previous:
                # Unknown is a stable state observation, not a repeated execution.
                if observation.key != "unknown" and json.loads(previous["payload"]) != json.loads(
                    json.dumps(asdict(observation))
                ):
                    raise InvalidWorkflow("Result key already identifies a different observation")
                if previous["applied"]:
                    return run, True
                task = work.tasks.get(project_id, run.task_id)
                if (
                    task.definition_revision == run.task_definition_revision
                    and task.status != "invalidated"
                    and run.apply(execution, observation, previous["id"])
                ):
                    work.workflows.mark_applied(previous["id"])
                    work.workflows.save(run)
                    return run, True
                return run, False
            task = work.tasks.get(project_id, run.task_id)
            result_id = uuid4().hex
            applicable = (
                task.definition_revision == run.task_definition_revision
                and task.status != "invalidated"
            )
            applied = applicable and run.apply(execution, observation, result_id)
            work.workflows.add_result(result_id, attempt_id, observation, applied)
            if applied:
                work.workflows.save(run)
                if run.status == "completed":
                    work.tasks.change(task, task.revision, reason=run.reason)
            return run, applied

    def revise(
        self,
        project_id,
        run_id,
        *,
        expected_revision,
        definition,
        inputs,
        reason,
        correction_source_id=None,
        invalidate=(),
    ):
        """Preserve unchanged phase evidence; invalidate changed targets and dependents.

        Method edits retain required IDs and goal. Goal/scope changes must reference
        the correction already applied to the task. Affected outstanding mutations
        must first be reconciled: revising must not hide unknown external effects.
        """
        if not reason.strip():
            raise InvalidWorkflow("A procedure change needs a reason")
        definition.validate(inputs)
        with self.database.transaction(write=True) as work:
            run = work.workflows.get(project_id, run_id)
            if run.revision != expected_revision:
                raise RevisionConflict("Workflow changed")
            task = work.tasks.get(project_id, run.task_id)
            if task.status == "invalidated":
                raise InvalidWorkflow("Cancelled task cannot resume a workflow")
            if correction_source_id:
                source = work.tasks.source(project_id, correction_source_id)
                if source.kind != "correction" or task.source_id != source.id:
                    raise InvalidWorkflow("Scope changes require the current task correction")
            elif task.definition_revision != run.task_definition_revision:
                raise InvalidWorkflow("Task correction must be reconciled explicitly")
            old = {p.id: p for p in run.definition.phases}
            new = {p.id: p for p in definition.phases}
            if not correction_source_id:
                if definition.purpose != run.definition.purpose:
                    raise InvalidWorkflow("Method changes cannot override the original goal")
                for key, phase in old.items():
                    if phase.required and (
                        key not in new
                        or not new[key].required
                        or new[key].when != phase.when
                        or not set(phase.conditions) <= set(new[key].conditions)
                        or new[key].reviewer != phase.reviewer
                    ):
                        raise InvalidWorkflow("Method changes cannot erase required conditions")
            affected = set(invalidate) | {
                k for k in old.keys() | new.keys() if old.get(k) != new.get(k)
            }
            if not set(invalidate) <= new.keys():
                raise InvalidWorkflow("Invalidation names an unknown phase")
            # Input bindings affect actions/review context, so unknown dependencies
            # are conservatively invalidated; unchanged inputs preserve valid work.
            if inputs != run.inputs:
                affected.update(old)
            for phase in definition.phases:
                if set(phase.depends_on) & affected:
                    affected.add(phase.id)
            for key in affected & old.keys():
                state = run.states[key]
                if old[key].mutation and state["status"] in {"running", "waiting"}:
                    raise InvalidWorkflow(
                        "Reconcile outstanding external mutation before revising it"
                    )
            states = {}
            for phase in definition.phases:
                state = run.states.get(phase.id)
                states[phase.id] = (
                    state
                    if state and phase.id not in affected
                    else run.fresh_state(state["generation"] + 1 if state else 1)
                )
                # Method revisions must not reset retry budgets to evade finite loops.
                if state and not correction_source_id:
                    states[phase.id]["attempts"] = state["attempts"]
                    states[phase.id]["failures"] = state["failures"]
                    states[phase.id]["defects"] = state["defects"]
            run.definition, run.inputs, run.states = definition, dict(inputs), states
            run.task_definition_revision = task.definition_revision
            run.definition_revision += 1
            run.status, run.reason = "active", reason
            run.finish()
            work.workflows.definition(run, reason, correction_source_id)
            work.workflows.save(run)
            if task.status == "succeeded":
                work.tasks.change(task, task.revision, status="pending", reason=reason)
            return run

    def yield_run(self, project_id, run_id, *, expected_revision, reason):
        if not reason.strip():
            raise InvalidWorkflow("Actual interruption/wait reason is required")
        with self.database.transaction(write=True) as work:
            run = self.checked(work, project_id, run_id, expected_revision)
            if run.status == "completed":
                return run
            run.events.append(dict(kind="yield", reason=reason, revision=run.revision))
            run.status, run.reason = "paused", reason
            work.workflows.save(run)
            return run

    def resume(self, project_id, run_id, *, expected_revision):
        with self.database.transaction(write=True) as work:
            run = self.checked(work, project_id, run_id, expected_revision)
            if run.status == "paused":
                run.events.append(dict(kind="resume", reason=run.reason, revision=run.revision))
                run.status = "active"
                work.workflows.save(run)
            # Running/waiting phases still require reconciliation, not resubmission.
            return run

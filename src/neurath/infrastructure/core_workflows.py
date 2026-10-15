"""Workflow persistence within a request-local unit of work."""

import json
from dataclasses import asdict

from sqlalchemy import insert, select, update

from neurath.domain.core import ContextNotFound, RevisionConflict
from neurath.domain.workflows import Definition, Execution, Run
from neurath.infrastructure import core_schema as s


class SqlWorkflows:
    def __init__(self, connection):
        self.connection = connection

    def get(self, project_id, run_id):
        data = self.connection.execute(
            select(s.workflow_runs.c.payload).where(
                s.workflow_runs.c.id == run_id, s.workflow_runs.c.project_id == project_id
            )
        ).scalar_one_or_none()
        if data is None:
            raise ContextNotFound("Run does not exist in this project")
        return Run.from_dict(json.loads(data))

    def for_task(self, task_id):
        return tuple(
            Run.from_dict(json.loads(data))
            for data in self.connection.execute(
                select(s.workflow_runs.c.payload).where(s.workflow_runs.c.task_id == task_id)
            ).scalars()
        )

    def create(self, run):
        self.connection.execute(
            insert(s.workflow_runs).values(
                id=run.id,
                project_id=run.project_id,
                task_id=run.task_id,
                revision=run.revision,
                payload=json.dumps(run.to_dict()),
            )
        )
        self.definition(run, "Selected procedure", None)

    def save(self, run):
        old = run.revision
        run.revision += 1
        changed = self.connection.execute(
            update(s.workflow_runs)
            .where(s.workflow_runs.c.id == run.id, s.workflow_runs.c.revision == old)
            .values(revision=run.revision, payload=json.dumps(run.to_dict()))
        )
        if changed.rowcount != 1:
            raise RevisionConflict("Workflow changed; read current state")

    def definition(self, run, reason, source_id):
        self.connection.execute(
            insert(s.workflow_definitions).values(
                run_id=run.id,
                revision=run.definition_revision,
                payload=json.dumps(run.to_dict()),
                reason=reason,
                source_id=source_id,
            )
        )

    def add_attempt(self, execution):
        self.connection.execute(
            insert(s.workflow_attempts).values(
                id=execution.id, run_id=execution.run_id, payload=json.dumps(asdict(execution))
            )
        )

    def attempt(self, run_id, attempt_id):
        data = self.connection.execute(
            select(s.workflow_attempts.c.payload).where(
                s.workflow_attempts.c.id == attempt_id, s.workflow_attempts.c.run_id == run_id
            )
        ).scalar_one_or_none()
        if data is None:
            raise ContextNotFound("Attempt does not belong to run")
        values = json.loads(data)
        values["phase"] = Definition.from_dict(
            dict(name="snapshot", version="snapshot", purpose="snapshot", phases=[values["phase"]])
        ).phases[0]
        return Execution(**values)

    def result(self, attempt_id, key):
        row = (
            self.connection.execute(
                select(s.workflow_results).where(
                    s.workflow_results.c.attempt_id == attempt_id,
                    s.workflow_results.c.event_key == key,
                )
            )
            .mappings()
            .first()
        )
        return dict(row) if row else None

    def mark_applied(self, result_id):
        self.connection.execute(
            update(s.workflow_results).where(s.workflow_results.c.id == result_id).values(applied=1)
        )

    def add_result(self, result_id, attempt_id, observation, applied):
        self.connection.execute(
            insert(s.workflow_results).values(
                id=result_id,
                attempt_id=attempt_id,
                event_key=observation.key,
                payload=json.dumps(asdict(observation)),
                applied=int(applied),
            )
        )

    def history(self, run_id):
        return {
            "definitions": tuple(
                dict(r)
                for r in self.connection.execute(
                    select(s.workflow_definitions)
                    .where(s.workflow_definitions.c.run_id == run_id)
                    .order_by(s.workflow_definitions.c.revision)
                ).mappings()
            ),
            "attempts": tuple(
                dict(r)
                for r in self.connection.execute(
                    select(s.workflow_attempts).where(s.workflow_attempts.c.run_id == run_id)
                ).mappings()
            ),
            "results": tuple(
                dict(r)
                for r in self.connection.execute(
                    select(s.workflow_results)
                    .join(s.workflow_attempts)
                    .where(s.workflow_attempts.c.run_id == run_id)
                ).mappings()
            ),
        }

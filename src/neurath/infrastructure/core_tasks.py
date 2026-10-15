"""SQL persistence for the task ledger; transaction owned by the calling use case."""

import json
from uuid import uuid4

from sqlalchemy import insert, select, update

from neurath.domain.core import ContextNotFound, RevisionConflict
from neurath.domain.tasks import Attempt, Source, Task, TaskResult
from neurath.infrastructure import core_schema as s


class SqlTasks:
    def __init__(self, connection):
        self.connection = connection

    def source(self, project_id, source_id):
        row = (
            self.connection.execute(
                select(s.sources).where(
                    s.sources.c.project_id == project_id, s.sources.c.id == source_id
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            raise ContextNotFound("Source does not exist in this project")
        return Source(**row)

    def add_source(self, **values):
        value = Source(id=uuid4().hex, **values)
        self.connection.execute(insert(s.sources).values(**vars(value)))
        return value

    def get(self, project_id, task_id):
        row = (
            self.connection.execute(
                select(s.tasks).where(s.tasks.c.project_id == project_id, s.tasks.c.id == task_id)
            )
            .mappings()
            .first()
        )
        if row is None:
            raise ContextNotFound("Task does not exist in this project")
        return Task(**row)

    def list(self, project_id, session_id):
        rows = self.connection.execute(
            select(s.tasks)
            .where(s.tasks.c.project_id == project_id, s.tasks.c.session_id == session_id)
            .order_by(s.tasks.c.id)
        ).mappings()
        return tuple(Task(**row) for row in rows)

    def create(self, **values):
        task = Task(
            id=uuid4().hex, status="pending", revision=1, definition_revision=1, reason="", **values
        )
        self.connection.execute(insert(s.tasks).values(**vars(task)))
        self.definition(task)
        return task

    def change(self, task, expected_revision, **values):
        changed = self.connection.execute(
            update(s.tasks)
            .where(s.tasks.c.id == task.id, s.tasks.c.revision == expected_revision)
            .values(revision=expected_revision + 1, **values)
        )
        if changed.rowcount != 1:
            raise RevisionConflict("Task changed; read the current task before retrying")
        return self.get(task.project_id, task.id)

    def definition(self, task):
        self.connection.execute(
            insert(s.task_definitions).values(
                task_id=task.id,
                revision=task.definition_revision,
                source_id=task.source_id,
                title=task.title,
                reason=task.reason,
            )
        )

    def definitions(self, task_id):
        return tuple(
            dict(row)
            for row in self.connection.execute(
                select(s.task_definitions)
                .where(s.task_definitions.c.task_id == task_id)
                .order_by(s.task_definitions.c.revision)
            ).mappings()
        )

    def dependencies(self, task_id):
        return tuple(
            self.connection.execute(
                select(s.task_dependencies.c.depends_on).where(
                    s.task_dependencies.c.task_id == task_id
                )
            ).scalars()
        )

    def add_dependency(self, task_id, depends_on):
        self.connection.execute(
            insert(s.task_dependencies).values(task_id=task_id, depends_on=depends_on)
        )

    def new_attempt(self, task):
        attempt = Attempt(uuid4().hex, task.id, task.definition_revision, "running")
        self.connection.execute(insert(s.task_attempts).values(**vars(attempt)))
        return attempt

    def attempt(self, task_id, attempt_id):
        row = (
            self.connection.execute(
                select(s.task_attempts).where(
                    s.task_attempts.c.id == attempt_id, s.task_attempts.c.task_id == task_id
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            raise ContextNotFound("Attempt does not belong to task")
        return Attempt(**row)

    def end_attempt(self, attempt_id, state):
        self.connection.execute(
            update(s.task_attempts).where(s.task_attempts.c.id == attempt_id).values(state=state)
        )

    def add_result(self, attempt_id, outcome, summary, references, remaining, applied):
        result = TaskResult(
            uuid4().hex, attempt_id, outcome, summary, tuple(references), remaining, applied
        )
        values = vars(result).copy()
        values["references_json"] = json.dumps(values.pop("references"))
        self.connection.execute(insert(s.task_results).values(**values))
        return result

    def results(self, task_id):
        rows = self.connection.execute(
            select(s.task_results).join(s.task_attempts).where(s.task_attempts.c.task_id == task_id)
        ).mappings()
        result = []
        for row in rows:
            values = dict(row)
            values["references"] = tuple(json.loads(values.pop("references_json")))
            values["applied"] = bool(values["applied"])
            result.append(TaskResult(**values))
        return tuple(result)

    def waits(self, task):
        return tuple(
            dict(row)
            for row in self.connection.execute(
                select(s.task_waits).where(
                    s.task_waits.c.task_id == task.id,
                    s.task_waits.c.definition_revision == task.definition_revision,
                    s.task_waits.c.resolved_by.is_(None),
                )
            ).mappings()
        )

    def add_wait(self, task, target, evidence, resolution_condition):
        wait_id = uuid4().hex
        self.connection.execute(
            insert(s.task_waits).values(
                id=wait_id,
                task_id=task.id,
                definition_revision=task.definition_revision,
                target=target,
                evidence=evidence,
                resolution_condition=resolution_condition,
            )
        )
        return wait_id

    def resolve_wait(self, wait_id, observation):
        self.connection.execute(
            update(s.task_waits).where(s.task_waits.c.id == wait_id).values(resolved_by=observation)
        )

    def open_attempt(self, task):
        row = (
            self.connection.execute(
                select(s.task_attempts).where(
                    s.task_attempts.c.task_id == task.id,
                    s.task_attempts.c.definition_revision == task.definition_revision,
                    s.task_attempts.c.state.in_(["running", "submitted"]),
                )
            )
            .mappings()
            .first()
        )
        return Attempt(**row) if row else None

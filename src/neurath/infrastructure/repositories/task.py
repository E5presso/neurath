"""SQLAlchemy adapter for the explicit Task repository contract."""

from typing import override

from sqlalchemy import select
from sqlalchemy.orm import Session

from neurath.application.ports.repositories.task import ITaskRepository
from neurath.domain.aggregates.task import Task
from neurath.domain.errors import ContextNotFound, RevisionConflict
from neurath.infrastructure.models.task import TaskModel


class TaskRepository(ITaskRepository):
    """Use the caller's Session and write reservation without owning commit or rollback."""

    def __init__(self, session: Session) -> None:
        """Bind the current request transaction explicitly."""
        self.session = session

    @override
    def add(self, value: Task) -> None:
        """Stage one new record; leave commit and rollback to the request."""
        self.session.add(TaskModel.from_domain(value))
        self.session.flush()

    @override
    def get(self, project_id: str, session_id: str, record_id: str) -> Task:
        """Return a record only inside the explicitly requested project and session."""
        return self._get_record(project_id, session_id, record_id).to_domain()

    @override
    def save(self, value: Task, expected_revision: int) -> None:
        """Persist an existing record after checking its prior state."""
        record = self._get_record(value.project_id, value.session_id, value.id)
        if record.revision != expected_revision or value.revision != expected_revision + 1:
            raise RevisionConflict("Task changed before saving")
        changed = TaskModel.from_domain(value)
        record.source_id = changed.source_id
        record.title = changed.title
        record.expected_outcome = changed.expected_outcome
        record.dependencies = changed.dependencies
        record.follows_task_id = changed.follows_task_id
        record.correction_source_id = changed.correction_source_id
        record.status = changed.status
        record.revision = changed.revision
        record.definition_revision = changed.definition_revision
        record.active_attempt_id = changed.active_attempt_id
        record.wait_target = changed.wait_target
        record.wait_condition = changed.wait_condition
        record.wait_continuation = changed.wait_continuation
        record.wait_evidence = changed.wait_evidence
        record.remaining_work = changed.remaining_work
        self.session.flush()

    @override
    def list(self, project_id: str, session_id: str) -> tuple[Task, ...]:
        """Read all matching records without projecting away failures or invalidations."""
        records = self.session.scalars(
            select(TaskModel)
            .where(TaskModel.project_id == project_id, TaskModel.session_id == session_id)
            .order_by(TaskModel.id)
        ).all()
        return tuple(record.to_domain() for record in records)

    def _get_record(self, project_id: str, session_id: str, record_id: str) -> TaskModel:
        """Find a scoped record without accepting identifiers from another context."""
        record = self.session.scalar(
            select(TaskModel).where(
                TaskModel.project_id == project_id,
                TaskModel.session_id == session_id,
                TaskModel.id == record_id,
            )
        )
        if record is None:
            raise ContextNotFound("Task does not exist in this project and session")
        return record

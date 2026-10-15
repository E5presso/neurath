"""SQLAlchemy adapter for the explicit TaskAttempt repository contract."""

from typing import override

from sqlalchemy import select
from sqlalchemy.orm import Session

from neurath.application.ports.repositories.task_attempt import IAttemptRepository
from neurath.domain.aggregates.task_attempt import TaskAttempt
from neurath.domain.errors import ContextNotFound, InvalidTaskOperation
from neurath.infrastructure.models.task_attempt import AttemptModel


class AttemptRepository(IAttemptRepository):
    """Use the caller's Session and write reservation without owning commit or rollback."""

    def __init__(self, session: Session) -> None:
        """Bind the current request transaction explicitly."""
        self.session = session

    @override
    def add(self, value: TaskAttempt) -> None:
        """Stage one new record; leave commit and rollback to the request."""
        self.session.add(AttemptModel.from_domain(value))
        self.session.flush()

    @override
    def get(self, project_id: str, session_id: str, record_id: str) -> TaskAttempt:
        """Return a record only inside the explicitly requested project and session."""
        return self._get_record(project_id, session_id, record_id).to_domain()

    @override
    def save(self, value: TaskAttempt) -> None:
        """Persist an existing record after checking its prior state."""
        record = self._get_record(value.project_id, value.session_id, value.id)
        if record.outcome is not None:
            raise InvalidTaskOperation("Attempt result is already recorded")
        changed = AttemptModel.from_domain(value)
        record.task_id = changed.task_id
        record.definition_revision = changed.definition_revision
        record.executor = changed.executor
        record.outcome = changed.outcome
        record.summary = changed.summary
        record.evidence = changed.evidence
        record.remaining_work = changed.remaining_work
        record.submission_summary = changed.submission_summary
        record.submission_evidence = changed.submission_evidence
        self.session.flush()

    @override
    def list(self, project_id: str, session_id: str, task_id: str) -> tuple[TaskAttempt, ...]:
        """Read all matching records without projecting away failures or invalidations."""
        records = self.session.scalars(
            select(AttemptModel)
            .where(
                AttemptModel.project_id == project_id,
                AttemptModel.session_id == session_id,
                AttemptModel.task_id == task_id,
            )
            .order_by(AttemptModel.id)
        ).all()
        return tuple(record.to_domain() for record in records)

    def _get_record(self, project_id: str, session_id: str, record_id: str) -> AttemptModel:
        """Find a scoped record without accepting identifiers from another context."""
        record = self.session.scalar(
            select(AttemptModel).where(
                AttemptModel.project_id == project_id,
                AttemptModel.session_id == session_id,
                AttemptModel.id == record_id,
            )
        )
        if record is None:
            raise ContextNotFound("TaskAttempt does not exist in this project and session")
        return record

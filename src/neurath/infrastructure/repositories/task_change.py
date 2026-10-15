"""SQLAlchemy adapter for the explicit TaskChange repository contract."""

from typing import override

from sqlalchemy import select
from sqlalchemy.orm import Session

from neurath.application.ports.repositories.task_change import IChangeRepository
from neurath.domain.aggregates.task_change import TaskChange
from neurath.infrastructure.models.task_change import ChangeModel


class ChangeRepository(IChangeRepository):
    """Use the caller's Session and write reservation without owning commit or rollback."""

    def __init__(self, session: Session) -> None:
        """Bind the current request transaction explicitly."""
        self.session = session

    @override
    def add(self, value: TaskChange) -> None:
        """Stage one new record; leave commit and rollback to the request."""
        self.session.add(ChangeModel.from_domain(value))
        self.session.flush()

    @override
    def list(self, project_id: str, session_id: str, task_id: str) -> tuple[TaskChange, ...]:
        """Read all matching records without projecting away failures or invalidations."""
        records = self.session.scalars(
            select(ChangeModel)
            .where(
                ChangeModel.project_id == project_id,
                ChangeModel.session_id == session_id,
                ChangeModel.task_id == task_id,
            )
            .order_by(ChangeModel.revision)
        ).all()
        return tuple(record.to_domain() for record in records)

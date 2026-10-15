"""SQLAlchemy adapter for the explicit RequestSource repository contract."""

from typing import override

from sqlalchemy import select
from sqlalchemy.orm import Session

from neurath.application.ports.repositories.request_source import ISourceRepository
from neurath.domain.aggregates.request_source import RequestSource
from neurath.domain.errors import ContextNotFound
from neurath.infrastructure.models.request_source import SourceModel


class SourceRepository(ISourceRepository):
    """Use the caller's Session and write reservation without owning commit or rollback."""

    def __init__(self, session: Session) -> None:
        """Bind the current request transaction explicitly."""
        self.session = session

    @override
    def add(self, value: RequestSource) -> None:
        """Stage one new record; leave commit and rollback to the request."""
        self.session.add(SourceModel.from_domain(value))
        self.session.flush()

    @override
    def get(self, project_id: str, record_id: str) -> RequestSource:
        """Resolve an explicit source ID within the project, retaining its origin session."""
        return self._get_record(project_id, record_id).to_domain()

    @override
    def list(self, project_id: str, session_id: str) -> tuple[RequestSource, ...]:
        """Read all matching records without projecting away failures or invalidations."""
        records = self.session.scalars(
            select(SourceModel)
            .where(SourceModel.project_id == project_id, SourceModel.session_id == session_id)
            .order_by(SourceModel.id)
        ).all()
        return tuple(record.to_domain() for record in records)

    def _get_record(self, project_id: str, record_id: str) -> SourceModel:
        """Find a scoped record without accepting identifiers from another context."""
        record = self.session.scalar(
            select(SourceModel).where(
                SourceModel.project_id == project_id,
                SourceModel.id == record_id,
            )
        )
        if record is None:
            raise ContextNotFound("RequestSource does not exist in this project")
        return record

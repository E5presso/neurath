"""SQLAlchemy repository for scoped host-session observations."""

from typing import override

from sqlalchemy import select
from sqlalchemy.orm import Session

from neurath.application.ports.repositories.session import ISessionRepository
from neurath.domain.aggregates.session import HostSession
from neurath.domain.errors import ContextNotFound, RevisionConflict
from neurath.infrastructure.models.session import SessionModel


class SessionRepository(ISessionRepository):
    """Use the caller's write lock and ORM Session for atomic revision changes."""

    def __init__(self, session: Session) -> None:
        """Bind one existing request transaction, never a cached connection."""
        self.session = session

    @override
    def find(self, project_id: str, provider: str, host_session_id: str) -> HostSession | None:
        """Find a native identifier only inside its project and provider scope."""
        record = self.session.scalar(
            select(SessionModel).where(
                SessionModel.project_id == project_id,
                SessionModel.provider == provider,
                SessionModel.host_session_id == host_session_id,
            )
        )
        if record is None:
            return None
        return record.to_domain()

    @override
    def get(self, project_id: str, session_id: str) -> HostSession:
        """Reject session identifiers belonging to another project."""
        record = self._get_record(project_id, session_id)
        return record.to_domain()

    def _get_record(self, project_id: str, session_id: str) -> SessionModel:
        """Read a scoped ORM record within the current transaction."""
        record = self.session.scalar(
            select(SessionModel).where(
                SessionModel.project_id == project_id, SessionModel.id == session_id
            )
        )
        if record is None:
            raise ContextNotFound("Session does not exist in the requested project")
        return record

    @override
    def add(self, session: HostSession) -> None:
        """Stage and flush a new observation without taking ownership of commit."""
        self.session.add(SessionModel.from_domain(session))
        self.session.flush()

    @override
    def save(self, session: HostSession, expected_revision: int) -> None:
        """Check revision under BEGIN IMMEDIATE and flush an explicit ORM update."""
        record = self._get_record(session.project_id, session.id)
        if record.revision != expected_revision or session.revision != expected_revision + 1:
            raise RevisionConflict("Session changed; read current context before updating")
        record.working_directory = session.working_directory
        record.revision = session.revision
        self.session.flush()

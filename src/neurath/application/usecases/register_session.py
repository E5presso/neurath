"""Implement the register session operation with explicit repository dependencies."""

from typing import override
from uuid import uuid4

from neurath.application.ports.repositories.project import IProjectRepository
from neurath.application.ports.repositories.session import ISessionRepository
from neurath.application.ports.usecases.register_session import (
    IRegisterSessionUseCase,
    RegisterSessionCommand,
)
from neurath.domain.aggregates.session import HostSession, SessionContext


class RegisterSessionUseCase(IRegisterSessionUseCase):
    """Coordinate project and session rules without owning persistence lifecycle."""

    def __init__(self, projects: IProjectRepository, sessions: ISessionRepository) -> None:
        """Bind repositories belonging to a single request transaction."""
        self.projects = projects
        self.sessions = sessions

    @override
    def execute(self, request: RegisterSessionCommand) -> SessionContext:
        """Apply the requested operation and return immutable, detached context."""
        if not request.provider.strip() or not request.host_session_id.strip():
            raise ValueError("provider and host_session_id must be non-empty")
        project = self.projects.resolve(request.location)
        session = self.sessions.find(project.id, request.provider, request.host_session_id)
        if session is None:
            session = HostSession(
                id=str(uuid4()),
                project_id=project.id,
                provider=request.provider,
                host_session_id=request.host_session_id,
                working_directory=request.location.working_directory,
                revision=1,
            )
            self.sessions.add(session)
        return SessionContext(project=project, session=session)

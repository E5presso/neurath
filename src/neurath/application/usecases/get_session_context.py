"""Implement the get session context operation with explicit repository dependencies."""

from typing import override

from neurath.application.ports.repositories.project import IProjectRepository
from neurath.application.ports.repositories.session import ISessionRepository
from neurath.application.ports.usecases.get_session_context import (
    GetSessionContextQuery,
    IGetSessionContextUseCase,
)
from neurath.domain.aggregates.session import SessionContext


class GetSessionContextUseCase(IGetSessionContextUseCase):
    """Coordinate project and session rules without owning persistence lifecycle."""

    def __init__(self, projects: IProjectRepository, sessions: ISessionRepository) -> None:
        """Bind repositories belonging to a single request transaction."""
        self.projects = projects
        self.sessions = sessions

    @override
    def execute(self, request: GetSessionContextQuery) -> SessionContext:
        """Apply the requested operation and return immutable, detached context."""
        session = self.sessions.get(request.project_id, request.session_id)
        project = self.projects.get(request.project_id)
        return SessionContext(project=project, session=session)

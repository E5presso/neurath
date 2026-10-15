"""Implement the move session operation with explicit repository dependencies."""

from typing import override

from neurath.application.ports.repositories.project import IProjectRepository
from neurath.application.ports.repositories.session import ISessionRepository
from neurath.application.ports.usecases.move_session import IMoveSessionUseCase, MoveSessionCommand
from neurath.domain.aggregates.session import SessionContext
from neurath.domain.errors import ContextNotFound


class MoveSessionUseCase(IMoveSessionUseCase):
    """Coordinate project and session rules without owning persistence lifecycle."""

    def __init__(self, projects: IProjectRepository, sessions: ISessionRepository) -> None:
        """Bind repositories belonging to a single request transaction."""
        self.projects = projects
        self.sessions = sessions

    @override
    def execute(self, request: MoveSessionCommand) -> SessionContext:
        """Apply the requested operation and return immutable, detached context."""
        session = self.sessions.get(request.project_id, request.session_id)
        project = self.projects.resolve(request.location)
        if project.id != request.project_id:
            raise ContextNotFound("Working directory belongs to another project")
        changed = session.move(request.location.working_directory, request.expected_revision)
        self.sessions.save(changed, request.expected_revision)
        return SessionContext(project=project, session=changed)

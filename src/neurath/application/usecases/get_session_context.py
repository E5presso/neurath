"""Implement the get session context operation with explicit repository dependencies."""

from dataclasses import dataclass

from neurath.application.context import SessionContext
from neurath.application.ports.repositories.project import IProjectRepository
from neurath.application.ports.repositories.session import ISessionRepository


@dataclass(frozen=True)
class GetSessionContextQuery:
    """Explicit immutable input for one get session context request.

    Attributes:
        project_id: Stable identifier of the project to address.
        session_id: Identifier of the session within the addressed project.
    """

    project_id: str
    session_id: str


class GetSessionContextUseCase:
    """Coordinate project and session rules without owning persistence lifecycle."""

    def __init__(self, projects: IProjectRepository, sessions: ISessionRepository) -> None:
        """Bind repositories belonging to a single request transaction.

        Args:
            projects: Project lookup and registration dependency for this request.
            sessions: Session persistence port for this request.
        """
        self.projects = projects
        self.sessions = sessions

    def execute(self, request: GetSessionContextQuery) -> SessionContext:
        """Apply the requested operation and return immutable, detached context.

        Args:
            request: Explicit command or query supplied by the request boundary.

        Returns:
            SessionContext: Detached project and session entities after the operation.
        """
        session = self.sessions.get(request.project_id, request.session_id)
        project = self.projects.get(request.project_id)
        return SessionContext.from_entities(project, session)

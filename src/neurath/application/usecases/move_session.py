"""Implement the move session operation with explicit repository dependencies."""

from dataclasses import dataclass

from neurath.application.context import SessionContext
from neurath.application.ports.repositories.session import ISessionRepository
from neurath.application.usecases.register_project import RegisterProjectUseCase
from neurath.domain.errors import ContextNotFound
from neurath.domain.observations import DirectoryObservation


@dataclass(frozen=True)
class MoveSessionCommand:
    """Explicit immutable input for one move session request.

    Attributes:
        project_id: Stable identifier of the project to address.
        session_id: Identifier of the session within the addressed project.
        observation: Canonical external facts used by project identity rules.
        expected_revision: Session revision observed before requesting a move.
    """

    project_id: str
    session_id: str
    observation: DirectoryObservation
    expected_revision: int


class MoveSessionUseCase:
    """Coordinate project and session rules without owning persistence lifecycle."""

    def __init__(self, projects: RegisterProjectUseCase, sessions: ISessionRepository) -> None:
        """Bind repositories belonging to a single request transaction.

        Args:
            projects: Project lookup and registration dependency for this request.
            sessions: Session persistence port for this request.
        """
        self.projects = projects
        self.sessions = sessions

    def execute(self, request: MoveSessionCommand) -> SessionContext:
        """Apply the requested operation and return immutable, detached context.

        Args:
            request: Explicit command or query supplied by the request boundary.

        Returns:
            SessionContext: Detached project and session entities after the operation.

        Raises:
            ContextNotFound: The addressed project or session does not exist in the requested scope.
        """
        session = self.sessions.get(request.project_id, request.session_id)
        project = self.projects.execute(request.observation)
        if project.id != request.project_id:
            raise ContextNotFound("Working directory belongs to another project")
        session.move(request.observation.working_directory, request.expected_revision)
        session = self.sessions.save(session)
        return SessionContext.from_entities(project, session)

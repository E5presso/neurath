"""Implement the register session operation with explicit repository dependencies."""

from dataclasses import dataclass

from neurath.application.context import SessionContext
from neurath.application.ports.repositories.session import ISessionRepository
from neurath.application.usecases.register_project import RegisterProjectUseCase
from neurath.domain.aggregates.session import HostSession
from neurath.domain.observations import DirectoryObservation


@dataclass(frozen=True)
class RegisterSessionCommand:
    """Explicit immutable input for one register session request.

    Attributes:
        observation: Canonical external facts used by project identity rules.
        provider: Host provider namespace for the native session identifier.
        host_session_id: Native session identifier supplied by the host provider.
    """

    observation: DirectoryObservation
    provider: str
    host_session_id: str


class RegisterSessionUseCase:
    """Coordinate project and session rules without owning persistence lifecycle."""

    def __init__(self, projects: RegisterProjectUseCase, sessions: ISessionRepository) -> None:
        """Bind repositories belonging to a single request transaction.

        Args:
            projects: Project lookup and registration dependency for this request.
            sessions: Session persistence port for this request.
        """
        self.projects = projects
        self.sessions = sessions

    def execute(self, request: RegisterSessionCommand) -> SessionContext:
        """Apply the requested operation and return immutable, detached context.

        Args:
            request: Explicit command or query supplied by the request boundary.

        Returns:
            SessionContext: Detached project and session entities after the operation.
        """
        project = self.projects.execute(request.observation)
        session = self.sessions.find(project.id, request.provider, request.host_session_id)
        if session is None:
            session = HostSession.create(
                project_id=project.id,
                provider=request.provider,
                host_session_id=request.host_session_id,
                working_directory=request.observation.working_directory,
            )
            self.sessions.add(session)
        return SessionContext.from_entities(project, session)

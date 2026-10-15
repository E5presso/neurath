"""Dishka composition and resource lifetimes for independent core requests."""

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from dishka import Container, Provider, Scope, from_context, make_container, provide
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from neurath.application.ports.repositories.project import IProjectRepository
from neurath.application.ports.repositories.project_location import IProjectLocationRepository
from neurath.application.ports.repositories.session import ISessionRepository
from neurath.application.ports.services.directory_observer import IDirectoryObserver
from neurath.application.usecases.get_session_context import GetSessionContextUseCase
from neurath.application.usecases.move_session import MoveSessionUseCase
from neurath.application.usecases.register_project import RegisterProjectUseCase
from neurath.application.usecases.register_session import RegisterSessionUseCase
from neurath.infrastructure.database import create_database_engine
from neurath.infrastructure.directory_observer import GitDirectoryObserver
from neurath.infrastructure.repositories.project import ProjectRepository
from neurath.infrastructure.repositories.project_location import ProjectLocationRepository
from neurath.infrastructure.repositories.session import SessionRepository


@dataclass(frozen=True)
class DatabaseSettings:
    """Immutable configuration supplied to a short-lived composition container.

    Attributes:
        path: Explicit database path or None for the user-wide default.
        write: Whether the request may write to the existing database.
    """

    path: Path | None
    write: bool


class RequestProvider(Provider):
    """Declare actual constructor injection and framework-managed resource cleanup.

    Attributes:
        settings: Application-scoped storage settings supplied through context.
        observer: Request-scoped primitive directory observation adapter.
        projects: Request-scoped project repository implementation.
        locations: Request-scoped location repository implementation.
        sessions: Request-scoped session repository implementation.
        register_project: Request-scoped project registration use case.
        register_session: Request-scoped native session registration use case.
        move_session: Request-scoped session movement use case.
        get_context: Request-scoped session context query use case.
    """

    settings = from_context(provides=DatabaseSettings, scope=Scope.APP)
    observer = provide(GitDirectoryObserver, provides=IDirectoryObserver, scope=Scope.REQUEST)
    projects = provide(ProjectRepository, provides=IProjectRepository, scope=Scope.REQUEST)
    locations = provide(
        ProjectLocationRepository, provides=IProjectLocationRepository, scope=Scope.REQUEST
    )
    sessions = provide(SessionRepository, provides=ISessionRepository, scope=Scope.REQUEST)
    register_project = provide(RegisterProjectUseCase, scope=Scope.REQUEST)
    register_session = provide(RegisterSessionUseCase, scope=Scope.REQUEST)
    move_session = provide(MoveSessionUseCase, scope=Scope.REQUEST)
    get_context = provide(GetSessionContextUseCase, scope=Scope.REQUEST)

    @provide(scope=Scope.APP)
    def engine(self, settings: DatabaseSettings) -> Iterator[Engine]:
        """Create an unpooled engine and dispose it when the container closes.

        Args:
            settings: Immutable storage configuration for this request.

        Yields:
            Engine: Engine restricted to the requested SQLite access mode.
        """
        engine = create_database_engine(settings.path, write=settings.write)
        try:
            yield engine
        finally:
            engine.dispose()

    @provide(scope=Scope.REQUEST)
    def session(self, engine: Engine) -> Iterator[Session]:
        """Provide one ORM session and always close it without committing.

        Transaction commit and rollback belong to the caller's Session.begin().

        Args:
            engine: Engine resolved by the containing application scope.

        Yields:
            Session: Request-local ORM session shared by its repositories.
        """
        with Session(engine, expire_on_commit=False, close_resets_only=False) as session:
            yield session


def request_container(settings: DatabaseSettings) -> Container:
    """Build an independent composition container for a single host request.

    Args:
        settings: Storage path and access mode, without retained runtime state.

    Returns:
        Container: Dishka container whose caller must close after leaving the request scope.
    """
    return make_container(RequestProvider(), context={DatabaseSettings: settings})

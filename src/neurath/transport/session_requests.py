"""Compose individual session requests using SQLAlchemy's transaction lifecycle.

Git observation completes before opening SQLite. Each request owns a new ORM
Session, commits or rolls back through Session.begin, and closes before returning.
"""

from pathlib import Path

from sqlalchemy.orm import Session

from neurath.application.context import SessionContext
from neurath.application.ports.services.directory_observer import IDirectoryObserver
from neurath.application.usecases.get_session_context import (
    GetSessionContextQuery,
    GetSessionContextUseCase,
)
from neurath.application.usecases.move_session import MoveSessionCommand, MoveSessionUseCase
from neurath.application.usecases.register_session import (
    RegisterSessionCommand,
    RegisterSessionUseCase,
)
from neurath.infrastructure.database import verify_schema
from neurath.infrastructure.providers import DatabaseSettings, request_container


def register_session(
    working_directory: str,
    provider: str,
    host_session_id: str,
    *,
    database_path: Path | None = None,
) -> SessionContext:
    """Register a native session idempotently without overwriting its newer directory.

    Args:
        working_directory: Existing directory supplied by the host request.
        provider: Host provider namespace for the native session identifier.
        host_session_id: Native session identifier supplied by the host provider.
        database_path: Explicit store path, or None for the user-wide default.

    Returns:
        SessionContext: Existing or newly registered host-session context.
    """
    container = request_container(DatabaseSettings(database_path, write=True))
    try:
        with container() as scope:
            observation = scope.get(IDirectoryObserver).observe(working_directory)
            request = RegisterSessionCommand(
                observation=observation, provider=provider, host_session_id=host_session_id
            )
            session = scope.get(Session)
            with session.begin():
                verify_schema(session)
                return scope.get(RegisterSessionUseCase).execute(request)
    finally:
        container.close()


def get_session_context(
    project_id: str, session_id: str, *, database_path: Path | None = None
) -> SessionContext:
    """Read exactly the requested project/session with a SQLite read-only connection.

    Args:
        project_id: Stable identifier of the project to address.
        session_id: Identifier of the session within the addressed project.
        database_path: Explicit store path, or None for the user-wide default.

    Returns:
        SessionContext: Current state of the explicitly addressed session.
    """
    request = GetSessionContextQuery(project_id=project_id, session_id=session_id)
    container = request_container(DatabaseSettings(database_path, write=False))
    try:
        with container() as scope:
            session = scope.get(Session)
            with session.begin():
                verify_schema(session)
                return scope.get(GetSessionContextUseCase).execute(request)
    finally:
        container.close()


def move_session(
    project_id: str,
    session_id: str,
    working_directory: str,
    expected_revision: int,
    *,
    database_path: Path | None = None,
) -> SessionContext:
    """Move a session inside its project only when the observed revision still matches.

    Args:
        project_id: Stable identifier of the project to address.
        session_id: Identifier of the session within the addressed project.
        working_directory: Existing directory supplied by the host request.
        expected_revision: Session revision observed before requesting a move.
        database_path: Explicit store path, or None for the user-wide default.

    Returns:
        SessionContext: Context containing the successfully advanced session revision.
    """
    container = request_container(DatabaseSettings(database_path, write=True))
    try:
        with container() as scope:
            observation = scope.get(IDirectoryObserver).observe(working_directory)
            request = MoveSessionCommand(
                project_id=project_id,
                session_id=session_id,
                observation=observation,
                expected_revision=expected_revision,
            )
            session = scope.get(Session)
            with session.begin():
                verify_schema(session)
                return scope.get(MoveSessionUseCase).execute(request)
    finally:
        container.close()

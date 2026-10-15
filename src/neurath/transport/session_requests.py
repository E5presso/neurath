"""Compose individual session requests using SQLAlchemy's transaction lifecycle.

Git observation completes before opening SQLite. Each request owns a new ORM
Session, commits or rolls back through Session.begin, and closes before returning.
"""

from pathlib import Path

from sqlalchemy.orm import Session

from neurath.application.ports.usecases.get_session_context import GetSessionContextQuery
from neurath.application.ports.usecases.move_session import MoveSessionCommand
from neurath.application.ports.usecases.register_session import RegisterSessionCommand
from neurath.application.usecases.get_session_context import GetSessionContextUseCase
from neurath.application.usecases.move_session import MoveSessionUseCase
from neurath.application.usecases.register_session import RegisterSessionUseCase
from neurath.domain.aggregates.session import SessionContext
from neurath.infrastructure.database import SqliteDatabase
from neurath.infrastructure.project_locator import GitProjectLocator
from neurath.infrastructure.repositories.project import ProjectRepository
from neurath.infrastructure.repositories.session import SessionRepository


def register_session(
    working_directory: str,
    provider: str,
    host_session_id: str,
    *,
    database_path: Path | None = None,
) -> SessionContext:
    """Register a native session idempotently without overwriting its newer directory."""
    location = GitProjectLocator().locate(working_directory)
    request = RegisterSessionCommand(
        location=location, provider=provider, host_session_id=host_session_id
    )
    database = SqliteDatabase(database_path)
    engine = database.create_engine(write=True)
    try:
        with Session(engine) as session, session.begin():
            database.verify_schema(session)
            use_case = RegisterSessionUseCase(
                ProjectRepository(session), SessionRepository(session)
            )
            return use_case.execute(request)
    finally:
        engine.dispose()


def get_session_context(
    project_id: str, session_id: str, *, database_path: Path | None = None
) -> SessionContext:
    """Read exactly the requested project/session with a SQLite read-only connection."""
    request = GetSessionContextQuery(project_id=project_id, session_id=session_id)
    database = SqliteDatabase(database_path)
    engine = database.create_engine(write=False)
    try:
        with Session(engine) as session, session.begin():
            database.verify_schema(session)
            use_case = GetSessionContextUseCase(
                ProjectRepository(session), SessionRepository(session)
            )
            return use_case.execute(request)
    finally:
        engine.dispose()


def move_session(
    project_id: str,
    session_id: str,
    working_directory: str,
    expected_revision: int,
    *,
    database_path: Path | None = None,
) -> SessionContext:
    """Move a session inside its project only when the observed revision still matches."""
    location = GitProjectLocator().locate(working_directory)
    request = MoveSessionCommand(
        project_id=project_id,
        session_id=session_id,
        location=location,
        expected_revision=expected_revision,
    )
    database = SqliteDatabase(database_path)
    engine = database.create_engine(write=True)
    try:
        with Session(engine) as session, session.begin():
            database.verify_schema(session)
            use_case = MoveSessionUseCase(ProjectRepository(session), SessionRepository(session))
            return use_case.execute(request)
    finally:
        engine.dispose()

"""Compose the record source request with a direct ORM transaction."""

from pathlib import Path

from sqlalchemy.orm import Session

from neurath.application.ports.usecases.record_source import RecordSourceCommand
from neurath.application.usecases.record_source import RecordSourceUseCase
from neurath.domain.aggregates.request_source import RequestSource
from neurath.infrastructure.database import SqliteDatabase
from neurath.infrastructure.repositories.request_source import SourceRepository
from neurath.infrastructure.repositories.session import SessionRepository


def record_source(
    request: RecordSourceCommand, *, database_path: Path | None = None
) -> RequestSource:
    """Preserve original attributed text without automatically creating any task."""
    database = SqliteDatabase(database_path)
    engine = database.create_engine(write=True)
    try:
        with Session(engine) as session, session.begin():
            database.verify_schema(session)
            SessionRepository(session).get(request.project_id, request.session_id)
            use_case = RecordSourceUseCase(SourceRepository(session))
            return use_case.execute(request)
    finally:
        engine.dispose()

"""Compose the get sources request with a direct ORM transaction."""

from pathlib import Path

from sqlalchemy.orm import Session

from neurath.application.ports.usecases.get_sources import GetSourcesQuery
from neurath.application.usecases.get_sources import GetSourcesUseCase
from neurath.domain.aggregates.request_source import RequestSource
from neurath.infrastructure.database import SqliteDatabase
from neurath.infrastructure.repositories.request_source import SourceRepository
from neurath.infrastructure.repositories.session import SessionRepository


def get_sources(
    request: GetSourcesQuery, *, database_path: Path | None = None
) -> tuple[RequestSource, ...]:
    """Read exact original text and corrections without turning observations into goals."""
    database = SqliteDatabase(database_path)
    engine = database.create_engine(write=False)
    try:
        with Session(engine) as session, session.begin():
            database.verify_schema(session)
            SessionRepository(session).get(request.project_id, request.session_id)
            use_case = GetSourcesUseCase(SourceRepository(session))
            return use_case.execute(request)
    finally:
        engine.dispose()

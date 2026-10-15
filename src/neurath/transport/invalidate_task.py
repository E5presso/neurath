"""Compose the invalidate task request with a direct ORM transaction."""

from pathlib import Path

from sqlalchemy.orm import Session

from neurath.application.ports.usecases.invalidate_task import InvalidateTaskCommand
from neurath.application.usecases.invalidate_task import InvalidateTaskUseCase
from neurath.domain.aggregates.task import Task
from neurath.infrastructure.database import SqliteDatabase
from neurath.infrastructure.repositories.request_source import SourceRepository
from neurath.infrastructure.repositories.session import SessionRepository
from neurath.infrastructure.repositories.task import TaskRepository
from neurath.infrastructure.repositories.task_change import ChangeRepository


def invalidate_task(request: InvalidateTaskCommand, *, database_path: Path | None = None) -> Task:
    """Apply a sourced cancellation without claiming a running attempt physically stopped."""
    database = SqliteDatabase(database_path)
    engine = database.create_engine(write=True)
    try:
        with Session(engine) as session, session.begin():
            database.verify_schema(session)
            SessionRepository(session).get(request.project_id, request.session_id)
            use_case = InvalidateTaskUseCase(
                SourceRepository(session), TaskRepository(session), ChangeRepository(session)
            )
            return use_case.execute(request)
    finally:
        engine.dispose()

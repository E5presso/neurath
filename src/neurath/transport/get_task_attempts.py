"""Compose the get task attempts request with a direct ORM transaction."""

from pathlib import Path

from sqlalchemy.orm import Session

from neurath.application.ports.usecases.get_task_attempts import GetTaskAttemptsQuery
from neurath.application.usecases.get_task_attempts import GetTaskAttemptsUseCase
from neurath.domain.aggregates.task_attempt import TaskAttempt
from neurath.infrastructure.database import SqliteDatabase
from neurath.infrastructure.repositories.session import SessionRepository
from neurath.infrastructure.repositories.task import TaskRepository
from neurath.infrastructure.repositories.task_attempt import AttemptRepository


def get_task_attempts(
    request: GetTaskAttemptsQuery, *, database_path: Path | None = None
) -> tuple[TaskAttempt, ...]:
    """Read all execution attempts including failed, unfinished and superseded attempts."""
    database = SqliteDatabase(database_path)
    engine = database.create_engine(write=False)
    try:
        with Session(engine) as session, session.begin():
            database.verify_schema(session)
            SessionRepository(session).get(request.project_id, request.session_id)
            use_case = GetTaskAttemptsUseCase(TaskRepository(session), AttemptRepository(session))
            return use_case.execute(request)
    finally:
        engine.dispose()

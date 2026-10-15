"""Compose the start task request with a direct ORM transaction."""

from pathlib import Path

from sqlalchemy.orm import Session

from neurath.application.ports.usecases.start_task import StartTaskCommand
from neurath.application.usecases.start_task import StartTaskUseCase
from neurath.domain.aggregates.task_attempt import TaskAttempt
from neurath.infrastructure.database import SqliteDatabase
from neurath.infrastructure.repositories.session import SessionRepository
from neurath.infrastructure.repositories.task import TaskRepository
from neurath.infrastructure.repositories.task_attempt import AttemptRepository
from neurath.infrastructure.repositories.task_change import ChangeRepository


def start_task(request: StartTaskCommand, *, database_path: Path | None = None) -> TaskAttempt:
    """Start one current definition, fencing duplicate starts and unfinished dependencies."""
    database = SqliteDatabase(database_path)
    engine = database.create_engine(write=True)
    try:
        with Session(engine) as session, session.begin():
            database.verify_schema(session)
            SessionRepository(session).get(request.project_id, request.session_id)
            use_case = StartTaskUseCase(
                TaskRepository(session), AttemptRepository(session), ChangeRepository(session)
            )
            return use_case.execute(request)
    finally:
        engine.dispose()

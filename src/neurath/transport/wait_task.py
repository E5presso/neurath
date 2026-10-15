"""Compose the wait task request with a direct ORM transaction."""

from pathlib import Path

from sqlalchemy.orm import Session

from neurath.application.ports.usecases.wait_task import WaitTaskCommand
from neurath.application.usecases.wait_task import WaitTaskUseCase
from neurath.domain.aggregates.task import Task
from neurath.infrastructure.database import SqliteDatabase
from neurath.infrastructure.repositories.session import SessionRepository
from neurath.infrastructure.repositories.task import TaskRepository
from neurath.infrastructure.repositories.task_change import ChangeRepository


def wait_task(request: WaitTaskCommand, *, database_path: Path | None = None) -> Task:
    """Record a concrete external dependency while leaving independent work ready."""
    database = SqliteDatabase(database_path)
    engine = database.create_engine(write=True)
    try:
        with Session(engine) as session, session.begin():
            database.verify_schema(session)
            SessionRepository(session).get(request.project_id, request.session_id)
            use_case = WaitTaskUseCase(TaskRepository(session), ChangeRepository(session))
            return use_case.execute(request)
    finally:
        engine.dispose()

"""Compose the correct task request with a direct ORM transaction."""

from pathlib import Path

from sqlalchemy.orm import Session

from neurath.application.ports.usecases.correct_task import CorrectTaskCommand
from neurath.application.usecases.correct_task import CorrectTaskUseCase
from neurath.domain.aggregates.task import Task
from neurath.infrastructure.database import SqliteDatabase
from neurath.infrastructure.repositories.request_source import SourceRepository
from neurath.infrastructure.repositories.session import SessionRepository
from neurath.infrastructure.repositories.task import TaskRepository
from neurath.infrastructure.repositories.task_change import ChangeRepository


def correct_task(request: CorrectTaskCommand, *, database_path: Path | None = None) -> Task:
    """Apply only explicitly corrected fields; retain unrelated tasks and original history."""
    database = SqliteDatabase(database_path)
    engine = database.create_engine(write=True)
    try:
        with Session(engine) as session, session.begin():
            database.verify_schema(session)
            SessionRepository(session).get(request.project_id, request.session_id)
            use_case = CorrectTaskUseCase(
                SourceRepository(session), TaskRepository(session), ChangeRepository(session)
            )
            return use_case.execute(request)
    finally:
        engine.dispose()

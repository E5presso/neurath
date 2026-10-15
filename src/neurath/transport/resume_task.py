"""Compose the resume task request with a direct ORM transaction."""

from pathlib import Path

from sqlalchemy.orm import Session

from neurath.application.ports.usecases.resume_task import ResumeTaskCommand
from neurath.application.usecases.resume_task import ResumeTaskUseCase
from neurath.domain.aggregates.task import Task
from neurath.infrastructure.database import SqliteDatabase
from neurath.infrastructure.repositories.session import SessionRepository
from neurath.infrastructure.repositories.task import TaskRepository
from neurath.infrastructure.repositories.task_change import ChangeRepository


def resume_task(request: ResumeTaskCommand, *, database_path: Path | None = None) -> Task:
    """Resume an externally waiting task only with observed release evidence."""
    database = SqliteDatabase(database_path)
    engine = database.create_engine(write=True)
    try:
        with Session(engine) as session, session.begin():
            database.verify_schema(session)
            SessionRepository(session).get(request.project_id, request.session_id)
            use_case = ResumeTaskUseCase(TaskRepository(session), ChangeRepository(session))
            return use_case.execute(request)
    finally:
        engine.dispose()

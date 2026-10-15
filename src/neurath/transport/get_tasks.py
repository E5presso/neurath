"""Compose the get tasks request with a direct ORM transaction."""

from pathlib import Path

from sqlalchemy.orm import Session

from neurath.application.ports.usecases.get_tasks import GetTasksQuery
from neurath.application.usecases.get_tasks import GetTasksUseCase
from neurath.domain.aggregates.task_projection import TaskProjection
from neurath.infrastructure.database import SqliteDatabase
from neurath.infrastructure.repositories.session import SessionRepository
from neurath.infrastructure.repositories.task import TaskRepository


def get_tasks(request: GetTasksQuery, *, database_path: Path | None = None) -> TaskProjection:
    """Project the complete current task collection and its independently ready work."""
    database = SqliteDatabase(database_path)
    engine = database.create_engine(write=False)
    try:
        with Session(engine) as session, session.begin():
            database.verify_schema(session)
            SessionRepository(session).get(request.project_id, request.session_id)
            use_case = GetTasksUseCase(TaskRepository(session))
            return use_case.execute(request)
    finally:
        engine.dispose()

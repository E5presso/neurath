"""Compose the get task history request with a direct ORM transaction."""

from pathlib import Path

from sqlalchemy.orm import Session

from neurath.application.ports.usecases.get_task_history import GetTaskHistoryQuery
from neurath.application.usecases.get_task_history import GetTaskHistoryUseCase
from neurath.domain.aggregates.task_change import TaskChange
from neurath.infrastructure.database import SqliteDatabase
from neurath.infrastructure.repositories.session import SessionRepository
from neurath.infrastructure.repositories.task import TaskRepository
from neurath.infrastructure.repositories.task_change import ChangeRepository


def get_task_history(
    request: GetTaskHistoryQuery, *, database_path: Path | None = None
) -> tuple[TaskChange, ...]:
    """Read every requirement snapshot and operation reason in revision order."""
    database = SqliteDatabase(database_path)
    engine = database.create_engine(write=False)
    try:
        with Session(engine) as session, session.begin():
            database.verify_schema(session)
            SessionRepository(session).get(request.project_id, request.session_id)
            use_case = GetTaskHistoryUseCase(TaskRepository(session), ChangeRepository(session))
            return use_case.execute(request)
    finally:
        engine.dispose()

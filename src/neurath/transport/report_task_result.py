"""Compose the report task result request with a direct ORM transaction."""

from pathlib import Path

from sqlalchemy.orm import Session

from neurath.application.ports.usecases.report_task_result import ReportTaskResultCommand
from neurath.application.usecases.report_task_result import ReportTaskResultUseCase
from neurath.domain.aggregates.task import Task
from neurath.infrastructure.database import SqliteDatabase
from neurath.infrastructure.repositories.session import SessionRepository
from neurath.infrastructure.repositories.task import TaskRepository
from neurath.infrastructure.repositories.task_attempt import AttemptRepository
from neurath.infrastructure.repositories.task_change import ChangeRepository


def report_task_result(
    request: ReportTaskResultCommand, *, database_path: Path | None = None
) -> Task:
    """Preserve an actual result; a stale attempt never closes a corrected requirement."""
    database = SqliteDatabase(database_path)
    engine = database.create_engine(write=True)
    try:
        with Session(engine) as session, session.begin():
            database.verify_schema(session)
            SessionRepository(session).get(request.project_id, request.session_id)
            use_case = ReportTaskResultUseCase(
                TaskRepository(session), AttemptRepository(session), ChangeRepository(session)
            )
            return use_case.execute(request)
    finally:
        engine.dispose()

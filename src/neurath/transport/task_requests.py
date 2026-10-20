"""태스크·원문·TODO 요청을 같은 stateless 코어와 트랜잭션으로 연결한다."""

from pathlib import Path

from spakky.plugins.sqlalchemy.persistency.session_manager import SessionManager
from spakky.plugins.sqlalchemy.persistency.transaction import Transaction

from neurath.application.task_context import (
    SourceContext,
    TaskBoardContext,
    TaskContext,
    TaskHistoryContext,
)
from neurath.application.usecases.correct_task import CorrectTaskCommand, CorrectTaskUseCase
from neurath.application.usecases.create_task import CreateTaskCommand, CreateTaskUseCase
from neurath.application.usecases.get_sources import GetSourcesQuery, GetSourcesUseCase
from neurath.application.usecases.get_task import GetTaskQuery, GetTaskUseCase
from neurath.application.usecases.get_tasks import GetTasksQuery, GetTasksUseCase
from neurath.application.usecases.invalidate_task import (
    InvalidateTaskCommand,
    InvalidateTaskUseCase,
)
from neurath.application.usecases.record_source import RecordSourceCommand, RecordSourceUseCase
from neurath.application.usecases.report_result import ReportResultCommand, ReportResultUseCase
from neurath.application.usecases.resume_task import ResumeTaskCommand, ResumeTaskUseCase
from neurath.application.usecases.start_task import StartTaskCommand, StartTaskUseCase
from neurath.application.usecases.submit_result import SubmitResultCommand, SubmitResultUseCase
from neurath.application.usecases.wait_task import WaitTaskCommand, WaitTaskUseCase
from neurath.infrastructure.database import verify_schema
from neurath.infrastructure.providers import DatabaseSettings, request_container


def record_source(
    request: RecordSourceCommand, *, database_path: Path | None = None
) -> SourceContext:
    """record_source 요청을 표준 트랜잭션에서 수행한다.

    Args:
        request: 범위와 명시적인 작업 입력.
        database_path: 명시적인 저장소 경로이며 None이면 사용자 단위 기본 경로.

    Returns:
        SourceContext: 원장과 일치하는 불변 결과.
    """
    with request_container(DatabaseSettings(database_path, write=True)) as scope:
        with scope.get(Transaction):
            verify_schema(scope.get(SessionManager).session)
            return scope.get(RecordSourceUseCase).execute(request)


def create_task(request: CreateTaskCommand, *, database_path: Path | None = None) -> TaskContext:
    """create_task 요청을 표준 트랜잭션에서 수행한다.

    Args:
        request: 범위와 명시적인 작업 입력.
        database_path: 명시적인 저장소 경로이며 None이면 사용자 단위 기본 경로.

    Returns:
        TaskContext: 원장과 일치하는 불변 결과.
    """
    with request_container(DatabaseSettings(database_path, write=True)) as scope:
        with scope.get(Transaction):
            verify_schema(scope.get(SessionManager).session)
            return scope.get(CreateTaskUseCase).execute(request)


def start_task(request: StartTaskCommand, *, database_path: Path | None = None) -> TaskContext:
    """start_task 요청을 표준 트랜잭션에서 수행한다.

    Args:
        request: 범위와 명시적인 작업 입력.
        database_path: 명시적인 저장소 경로이며 None이면 사용자 단위 기본 경로.

    Returns:
        TaskContext: 원장과 일치하는 불변 결과.
    """
    with request_container(DatabaseSettings(database_path, write=True)) as scope:
        with scope.get(Transaction):
            verify_schema(scope.get(SessionManager).session)
            return scope.get(StartTaskUseCase).execute(request)


def submit_result(
    request: SubmitResultCommand, *, database_path: Path | None = None
) -> TaskContext:
    """submit_result 요청을 표준 트랜잭션에서 수행한다.

    Args:
        request: 범위와 명시적인 작업 입력.
        database_path: 명시적인 저장소 경로이며 None이면 사용자 단위 기본 경로.

    Returns:
        TaskContext: 원장과 일치하는 불변 결과.
    """
    with request_container(DatabaseSettings(database_path, write=True)) as scope:
        with scope.get(Transaction):
            verify_schema(scope.get(SessionManager).session)
            return scope.get(SubmitResultUseCase).execute(request)


def report_result(
    request: ReportResultCommand, *, database_path: Path | None = None
) -> TaskContext:
    """report_result 요청을 표준 트랜잭션에서 수행한다.

    Args:
        request: 범위와 명시적인 작업 입력.
        database_path: 명시적인 저장소 경로이며 None이면 사용자 단위 기본 경로.

    Returns:
        TaskContext: 원장과 일치하는 불변 결과.
    """
    with request_container(DatabaseSettings(database_path, write=True)) as scope:
        with scope.get(Transaction):
            verify_schema(scope.get(SessionManager).session)
            return scope.get(ReportResultUseCase).execute(request)


def correct_task(request: CorrectTaskCommand, *, database_path: Path | None = None) -> TaskContext:
    """correct_task 요청을 표준 트랜잭션에서 수행한다.

    Args:
        request: 범위와 명시적인 작업 입력.
        database_path: 명시적인 저장소 경로이며 None이면 사용자 단위 기본 경로.

    Returns:
        TaskContext: 원장과 일치하는 불변 결과.
    """
    with request_container(DatabaseSettings(database_path, write=True)) as scope:
        with scope.get(Transaction):
            verify_schema(scope.get(SessionManager).session)
            return scope.get(CorrectTaskUseCase).execute(request)


def wait_task(request: WaitTaskCommand, *, database_path: Path | None = None) -> TaskContext:
    """wait_task 요청을 표준 트랜잭션에서 수행한다.

    Args:
        request: 범위와 명시적인 작업 입력.
        database_path: 명시적인 저장소 경로이며 None이면 사용자 단위 기본 경로.

    Returns:
        TaskContext: 원장과 일치하는 불변 결과.
    """
    with request_container(DatabaseSettings(database_path, write=True)) as scope:
        with scope.get(Transaction):
            verify_schema(scope.get(SessionManager).session)
            return scope.get(WaitTaskUseCase).execute(request)


def resume_task(request: ResumeTaskCommand, *, database_path: Path | None = None) -> TaskContext:
    """resume_task 요청을 표준 트랜잭션에서 수행한다.

    Args:
        request: 범위와 명시적인 작업 입력.
        database_path: 명시적인 저장소 경로이며 None이면 사용자 단위 기본 경로.

    Returns:
        TaskContext: 원장과 일치하는 불변 결과.
    """
    with request_container(DatabaseSettings(database_path, write=True)) as scope:
        with scope.get(Transaction):
            verify_schema(scope.get(SessionManager).session)
            return scope.get(ResumeTaskUseCase).execute(request)


def invalidate_task(
    request: InvalidateTaskCommand, *, database_path: Path | None = None
) -> TaskContext:
    """invalidate_task 요청을 표준 트랜잭션에서 수행한다.

    Args:
        request: 범위와 명시적인 작업 입력.
        database_path: 명시적인 저장소 경로이며 None이면 사용자 단위 기본 경로.

    Returns:
        TaskContext: 원장과 일치하는 불변 결과.
    """
    with request_container(DatabaseSettings(database_path, write=True)) as scope:
        with scope.get(Transaction):
            verify_schema(scope.get(SessionManager).session)
            return scope.get(InvalidateTaskUseCase).execute(request)


def get_tasks(request: GetTasksQuery, *, database_path: Path | None = None) -> TaskBoardContext:
    """get_tasks 요청을 표준 트랜잭션에서 수행한다.

    Args:
        request: 범위와 명시적인 작업 입력.
        database_path: 명시적인 저장소 경로이며 None이면 사용자 단위 기본 경로.

    Returns:
        TaskBoardContext: 원장과 일치하는 불변 결과.
    """
    with request_container(DatabaseSettings(database_path, write=False)) as scope:
        with scope.get(Transaction):
            verify_schema(scope.get(SessionManager).session)
            return scope.get(GetTasksUseCase).execute(request)


def get_task(request: GetTaskQuery, *, database_path: Path | None = None) -> TaskHistoryContext:
    """get_task 요청을 표준 트랜잭션에서 수행한다.

    Args:
        request: 범위와 명시적인 작업 입력.
        database_path: 명시적인 저장소 경로이며 None이면 사용자 단위 기본 경로.

    Returns:
        TaskHistoryContext: 원장과 일치하는 불변 결과.
    """
    with request_container(DatabaseSettings(database_path, write=False)) as scope:
        with scope.get(Transaction):
            verify_schema(scope.get(SessionManager).session)
            return scope.get(GetTaskUseCase).execute(request)


def get_sources(
    request: GetSourcesQuery, *, database_path: Path | None = None
) -> tuple[SourceContext, ...]:
    """get_sources 요청을 표준 트랜잭션에서 수행한다.

    Args:
        request: 범위와 명시적인 작업 입력.
        database_path: 명시적인 저장소 경로이며 None이면 사용자 단위 기본 경로.

    Returns:
        tuple[SourceContext, ...]: 원장과 일치하는 불변 결과.
    """
    with request_container(DatabaseSettings(database_path, write=False)) as scope:
        with scope.get(Transaction):
            verify_schema(scope.get(SessionManager).session)
            return scope.get(GetSourcesUseCase).execute(request)

"""프레임워크 저장소·테이블·세션·트랜잭션을 요청별로 구성한다."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path

from spakky.core.application.application_context import ApplicationContext
from spakky.core.pod.annotations.pod import Pod
from spakky.data.persistency.aggregate_collector import AggregateCollector
from spakky.data.persistency.repository import EntityNotFoundError, VersionConflictError
from spakky.plugins.sqlalchemy.common.config import SQLAlchemyConnectionConfig
from spakky.plugins.sqlalchemy.orm.schema_registry import SchemaRegistry
from spakky.plugins.sqlalchemy.orm.table import Table
from spakky.plugins.sqlalchemy.persistency.connection_manager import ConnectionManager
from spakky.plugins.sqlalchemy.persistency.session_manager import SessionManager
from spakky.plugins.sqlalchemy.persistency.transaction import Transaction
from sqlalchemy.exc import IntegrityError

from neurath.application.usecases.correct_task import CorrectTaskUseCase
from neurath.application.usecases.create_task import CreateTaskUseCase
from neurath.application.usecases.execute_phase import ExecutePhaseUseCase
from neurath.application.usecases.get_session_context import GetSessionContextUseCase
from neurath.application.usecases.get_sources import GetSourcesUseCase
from neurath.application.usecases.get_task import GetTaskUseCase
from neurath.application.usecases.get_tasks import GetTasksUseCase
from neurath.application.usecases.get_workflow import GetWorkflowUseCase
from neurath.application.usecases.handle_hook import HandleHookUseCase
from neurath.application.usecases.invalidate_task import InvalidateTaskUseCase
from neurath.application.usecases.move_session import MoveSessionUseCase
from neurath.application.usecases.prepare_phase import PreparePhaseUseCase
from neurath.application.usecases.record_source import RecordSourceUseCase
from neurath.application.usecases.register_project import RegisterProjectUseCase
from neurath.application.usecases.register_session import RegisterSessionUseCase
from neurath.application.usecases.report_phase import ReportPhaseUseCase
from neurath.application.usecases.report_result import ReportResultUseCase
from neurath.application.usecases.resume_execution import ResumeExecutionUseCase
from neurath.application.usecases.resume_task import ResumeTaskUseCase
from neurath.application.usecases.revise_workflow import ReviseWorkflowUseCase
from neurath.application.usecases.skip_phase import SkipPhaseUseCase
from neurath.application.usecases.start_task import StartTaskUseCase
from neurath.application.usecases.start_workflow import StartWorkflowUseCase
from neurath.application.usecases.submit_result import SubmitResultUseCase
from neurath.application.usecases.wait_task import WaitTaskUseCase
from neurath.domain.errors import ContextNotFound, ProjectIdentityConflict, RevisionConflict
from neurath.infrastructure.database import configure_sqlite_engine, database_url
from neurath.infrastructure.directory_observer import GitDirectoryObserverService
from neurath.infrastructure.models.execution import ExecutionModel
from neurath.infrastructure.models.project import ProjectLocationModel, ProjectModel
from neurath.infrastructure.models.request_source import RequestSourceModel
from neurath.infrastructure.models.session import SessionModel
from neurath.infrastructure.models.task import (
    TaskAttemptModel,
    TaskDefinitionModel,
    TaskDependencyModel,
    TaskModel,
    TaskWaitModel,
)
from neurath.infrastructure.models.workflow import (
    PhaseAttemptModel,
    PhaseDefinitionModel,
    WorkflowModel,
    WorkflowRevisionModel,
)
from neurath.infrastructure.models.writer import WriterModel
from neurath.infrastructure.phase_executor import (
    StderrWorkflowNotifierService,
    SubprocessPhaseExecutorService,
)
from neurath.infrastructure.repositories.execution import SQLAlchemyExecutionRepository
from neurath.infrastructure.repositories.project import SQLAlchemyProjectRepository
from neurath.infrastructure.repositories.request_source import SQLAlchemyRequestSourceRepository
from neurath.infrastructure.repositories.session import SQLAlchemySessionRepository
from neurath.infrastructure.repositories.task import SQLAlchemyTaskRepository
from neurath.infrastructure.repositories.workflow import SQLAlchemyWorkflowRepository
from neurath.infrastructure.repositories.writer import SQLAlchemyWriterRepository


@dataclass(frozen=True)
class DatabaseSettings:
    """요청이 지정한 저장소 경로와 접근 모드다.

    Attributes:
        path: 명시적인 데이터베이스 경로이며 None이면 사용자 단위 기본 경로.
        write: 쓰기 연결을 허용할지 여부.
    """

    path: Path | None
    write: bool


_request_config: ContextVar[SQLAlchemyConnectionConfig] = ContextVar("neurath_sqlalchemy_config")


@Pod()
def request_config() -> SQLAlchemyConnectionConfig:
    """현재 요청의 엔진 구성 중에 바인딩한 SQLAlchemy 설정을 제공한다.

    모듈 수준 팩토리이므로 Spakky의 모듈 스캔과 명시적 등록에서 모두 발견된다.
    설정은 엔진을 생성하는 동안만 ContextVar에 바인딩하고 즉시 이전 값으로 복원한다.
    바인딩 없이 직접 호출하면 ContextVar의 LookupError가 전파된다.

    Returns:
        SQLAlchemyConnectionConfig: 현재 요청의 경로·접근 모드를 가진 설정.
    """
    return _request_config.get()


@contextmanager
def request_container(settings: DatabaseSettings) -> Iterator[ApplicationContext]:
    """한 요청의 SQLite 연결·저장소·유스케이스를 구성하고 종료 시 자원을 정리한다.

    환경변수 변경 없이 요청 설정을 주입한다. 호출자는 반환된 컨테이너에서
    Transaction을 열어 유스케이스를 실행해야 하며, 이 함수 자체는 커밋하지 않는다.
    본문의 저장소 오류는 아래 도메인 오류로 변환하고 세션·컨테이너·엔진을 정리한다.

    Args:
        settings: 이번 요청에만 적용하는 경로와 접근 모드.

    Yields:
        ApplicationContext: 저장소와 트랜잭션을 조회하는 요청별 컨테이너.

    Raises:
        ContextNotFound: 기본 저장소가 요청한 aggregate를 찾지 못한 경우.
        RevisionConflict: 기본 저장소가 오래된 버전으로 저장하려 한 경우.
        ProjectIdentityConflict: 저장된 위치의 기존 소유자를 바꾸려 한 경우.
        IntegrityError: 위치 소유 충돌 이외의 무결성 위반이 발생한 경우.
    """
    config = SQLAlchemyConnectionConfig.model_construct(
        connection_string=database_url(settings.path, write=settings.write).render_as_string(
            hide_password=False
        ),
        support_async_mode=False,
    )
    context = ApplicationContext()
    context.add(request_config)
    context.add(ConnectionManager)
    with _request_config.set(config):
        connection = context.get(ConnectionManager)
    try:
        configure_sqlite_engine(connection.connection, write=settings.write, check_schema=True)
        for pod in (
            HandleHookUseCase,
            ResumeExecutionUseCase,
            SQLAlchemyExecutionRepository,
            SQLAlchemyWriterRepository,
            StartWorkflowUseCase,
            GetWorkflowUseCase,
            PreparePhaseUseCase,
            ReportPhaseUseCase,
            ReviseWorkflowUseCase,
            SkipPhaseUseCase,
            ExecutePhaseUseCase,
            SQLAlchemyWorkflowRepository,
            SubprocessPhaseExecutorService,
            StderrWorkflowNotifierService,
            SessionManager,
            Transaction,
            SchemaRegistry,
            AggregateCollector,
            GitDirectoryObserverService,
            SQLAlchemyProjectRepository,
            SQLAlchemySessionRepository,
            RegisterProjectUseCase,
            RegisterSessionUseCase,
            MoveSessionUseCase,
            GetSessionContextUseCase,
            SQLAlchemyRequestSourceRepository,
            SQLAlchemyTaskRepository,
            RecordSourceUseCase,
            CreateTaskUseCase,
            StartTaskUseCase,
            SubmitResultUseCase,
            ReportResultUseCase,
            CorrectTaskUseCase,
            WaitTaskUseCase,
            ResumeTaskUseCase,
            InvalidateTaskUseCase,
            GetTasksUseCase,
            GetTaskUseCase,
            GetSourcesUseCase,
        ):
            context.add(pod)
        for model in (
            ExecutionModel,
            WriterModel,
            WorkflowModel,
            WorkflowRevisionModel,
            PhaseDefinitionModel,
            PhaseAttemptModel,
            ProjectModel,
            ProjectLocationModel,
            SessionModel,
            RequestSourceModel,
            TaskModel,
            TaskDefinitionModel,
            TaskDependencyModel,
            TaskAttemptModel,
            TaskWaitModel,
        ):
            context.register_tag(Table.get(model))
        context.start()
        try:
            yield context
        except EntityNotFoundError as error:
            raise ContextNotFound(
                "Requested record does not exist in the requested scope"
            ) from error
        except VersionConflictError as error:
            raise RevisionConflict(
                "Stored record changed; read current context before updating"
            ) from error
        except IntegrityError as error:
            if "Location already belongs to another project" in str(error.orig):
                raise ProjectIdentityConflict(
                    "Location already belongs to another project"
                ) from error
            raise
        finally:
            try:
                context.get(SessionManager).close()
            finally:
                context.stop()
    finally:
        connection.dispose()

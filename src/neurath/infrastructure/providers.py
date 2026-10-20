"""프레임워크 저장소·테이블·세션·트랜잭션을 요청별로 구성한다."""

from collections.abc import Iterator
from contextlib import contextmanager
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

from neurath.application.usecases.get_session_context import GetSessionContextUseCase
from neurath.application.usecases.move_session import MoveSessionUseCase
from neurath.application.usecases.register_project import RegisterProjectUseCase
from neurath.application.usecases.register_session import RegisterSessionUseCase
from neurath.domain.errors import ContextNotFound, ProjectIdentityConflict, RevisionConflict
from neurath.infrastructure.database import configure_sqlite_engine, database_url
from neurath.infrastructure.directory_observer import GitDirectoryObserver
from neurath.infrastructure.models.project import ProjectLocationModel, ProjectModel
from neurath.infrastructure.models.session import SessionModel
from neurath.infrastructure.repositories.project import ProjectRepository
from neurath.infrastructure.repositories.session import SessionRepository


@dataclass(frozen=True)
class DatabaseSettings:
    """요청이 지정한 저장소 경로와 접근 모드다.

    Attributes:
        path: 명시적인 데이터베이스 경로이며 None이면 사용자 단위 기본 경로.
        write: 쓰기 연결을 허용할지 여부.
    """

    path: Path | None
    write: bool


@contextmanager
def request_container(settings: DatabaseSettings) -> Iterator[ApplicationContext]:
    """표준 프레임워크 구성요소를 등록하고 요청 종료 시 자원을 정리한다.

    환경변수를 바꾸지 않고 요청별 설정 인스턴스를 주입한다. 실제
    ConnectionManager·SessionManager·Transaction과 기본 저장소를 사용한다.

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
    connection = ConnectionManager(config)
    configure_sqlite_engine(connection.connection, write=settings.write)

    @Pod()
    def request_config() -> SQLAlchemyConnectionConfig:
        """요청별 설정을 전역 환경 변경 없이 제공한다.

        Returns:
            SQLAlchemyConnectionConfig: 이번 요청의 SQLite 접근 설정.
        """
        return config

    @Pod()
    def request_connection() -> ConnectionManager:
        """요청 경계에서 정리하는 실제 프레임워크 연결 관리자를 제공한다.

        Returns:
            ConnectionManager: 요청별 엔진을 보유한 프레임워크 구성요소.
        """
        return connection

    context = ApplicationContext()
    try:
        context.add(request_config)
        context.add(request_connection)
        for pod in (
            SessionManager,
            Transaction,
            SchemaRegistry,
            AggregateCollector,
            GitDirectoryObserver,
            ProjectRepository,
            SessionRepository,
            RegisterProjectUseCase,
            RegisterSessionUseCase,
            MoveSessionUseCase,
            GetSessionContextUseCase,
        ):
            context.add(pod)
        for model in (ProjectModel, ProjectLocationModel, SessionModel):
            context.register_tag(Table.get(model))
        context.start()
        try:
            yield context
        except EntityNotFoundError as error:
            raise ContextNotFound(
                "Project or session does not exist in the requested scope"
            ) from error
        except VersionConflictError as error:
            raise RevisionConflict(
                "Session changed; read current context before updating"
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

"""SQLAlchemy의 트랜잭션 수명에 따라 개별 세션 요청을 구성한다.

SQLite를 열기 전에 Git 관찰을 마친다. 각 요청은 새 ORM 세션을 소유하며
Session.begin으로 커밋 또는 롤백한 뒤 반환 전에 세션을 닫는다.
"""

from pathlib import Path

from sqlalchemy.orm import Session

from neurath.application.context import SessionContext
from neurath.application.ports.services.directory_observer import IDirectoryObserver
from neurath.application.usecases.get_session_context import (
    GetSessionContextQuery,
    GetSessionContextUseCase,
)
from neurath.application.usecases.move_session import MoveSessionCommand, MoveSessionUseCase
from neurath.application.usecases.register_session import (
    RegisterSessionCommand,
    RegisterSessionUseCase,
)
from neurath.infrastructure.database import verify_schema
from neurath.infrastructure.providers import DatabaseSettings, request_container


def register_session(
    working_directory: str,
    provider: str,
    host_session_id: str,
    *,
    database_path: Path | None = None,
) -> SessionContext:
    """더 최신인 작업 경로를 덮어쓰지 않고 네이티브 세션을 멱등적으로 등록한다.

    Args:
        working_directory: 호스트 요청이 제공한 기존 디렉터리.
        provider: 네이티브 세션 식별자의 호스트 공급자 이름 공간.
        host_session_id: 호스트 공급자가 전달한 네이티브 세션 식별자.
        database_path: 명시적인 저장소 경로이며 None이면 사용자 단위 기본 경로.

    Returns:
        SessionContext: 기존 또는 새로 등록한 호스트 세션 컨텍스트.
    """
    with request_container(DatabaseSettings(database_path, write=True)) as scope:
        observation = scope.get(IDirectoryObserver).observe(working_directory)
        request = RegisterSessionCommand(
            observation=observation, provider=provider, host_session_id=host_session_id
        )
        session = scope.get(Session)
        with session.begin():
            verify_schema(session)
            return scope.get(RegisterSessionUseCase).execute(request)


def get_session_context(
    project_id: str, session_id: str, *, database_path: Path | None = None
) -> SessionContext:
    """SQLite 읽기 전용 연결로 지정한 프로젝트와 세션만 조회한다.

    Args:
        project_id: 조회 대상 프로젝트의 안정적인 식별자.
        session_id: 지정한 프로젝트 안에 있는 세션의 식별자.
        database_path: 명시적인 저장소 경로이며 None이면 사용자 단위 기본 경로.

    Returns:
        SessionContext: 명시적으로 지정한 세션의 현재 상태.
    """
    request = GetSessionContextQuery(project_id=project_id, session_id=session_id)
    with request_container(DatabaseSettings(database_path, write=False)) as scope:
        session = scope.get(Session)
        with session.begin():
            verify_schema(session)
            return scope.get(GetSessionContextUseCase).execute(request)


def move_session(
    project_id: str,
    session_id: str,
    working_directory: str,
    expected_revision: int,
    *,
    database_path: Path | None = None,
) -> SessionContext:
    """관찰한 버전이 현재와 일치할 때만 프로젝트 안에서 세션을 이동한다.

    Args:
        project_id: 조회 대상 프로젝트의 안정적인 식별자.
        session_id: 지정한 프로젝트 안에 있는 세션의 식별자.
        working_directory: 호스트 요청이 제공한 기존 디렉터리.
        expected_revision: 이동 요청 전에 관찰한 세션 버전.
        database_path: 명시적인 저장소 경로이며 None이면 사용자 단위 기본 경로.

    Returns:
        SessionContext: 성공적으로 갱신한 세션 버전을 포함하는 컨텍스트.
    """
    with request_container(DatabaseSettings(database_path, write=True)) as scope:
        observation = scope.get(IDirectoryObserver).observe(working_directory)
        request = MoveSessionCommand(
            project_id=project_id,
            session_id=session_id,
            observation=observation,
            expected_revision=expected_revision,
        )
        session = scope.get(Session)
        with session.begin():
            verify_schema(session)
            return scope.get(MoveSessionUseCase).execute(request)

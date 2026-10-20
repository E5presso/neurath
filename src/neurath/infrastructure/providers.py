"""Spakky의 요청별 컨테이너에 실제 ORM 자원과 애플리케이션 의존성을 등록한다."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from spakky.core.application.application_context import ApplicationContext
from spakky.core.pod.annotations.pod import Pod
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from neurath.application.usecases.get_session_context import GetSessionContextUseCase
from neurath.application.usecases.move_session import MoveSessionUseCase
from neurath.application.usecases.register_project import RegisterProjectUseCase
from neurath.application.usecases.register_session import RegisterSessionUseCase
from neurath.infrastructure.database import create_database_engine
from neurath.infrastructure.directory_observer import GitDirectoryObserver
from neurath.infrastructure.repositories.project import ProjectRepository
from neurath.infrastructure.repositories.session import SessionRepository


@dataclass(frozen=True)
class DatabaseSettings:
    """하나의 요청이 소유하는 저장소의 접근 설정이다.

    Attributes:
        path: 명시적인 데이터베이스 경로이며 None이면 사용자 단위 기본 경로.
        write: 기존 데이터베이스에 쓰기를 허용할지 여부.
    """

    path: Path | None
    write: bool


@contextmanager
def request_container(settings: DatabaseSettings) -> Iterator[ApplicationContext]:
    """요청마다 Spakky 컨테이너를 구성하고 ORM 자원을 항상 정리한다.

    생성자 주입과 ABC 구현 선택은 Spakky가 담당한다. 컨테이너마다 같은
    ORM 세션을 주입하며 Session.begin은 호출자가 직접 소유한다.

    Args:
        settings: 상주 실행 상태를 포함하지 않는 저장 경로와 접근 모드.

    Yields:
        ApplicationContext: 요청의 저장소와 유스케이스를 조회하는 Spakky 컨테이너.
    """
    engine = create_database_engine(settings.path, write=settings.write)
    try:
        with Session(engine, expire_on_commit=False, close_resets_only=False) as orm_session:

            @Pod()
            def request_engine() -> Engine:
                """현재 요청이 소유하고 정리하는 실제 엔진을 제공한다.

                Returns:
                    Engine: 읽기 또는 쓰기 모드를 지정한 요청별 엔진.
                """
                return engine

            @Pod()
            def request_session() -> Session:
                """모든 저장소가 공유하는 요청별 ORM 세션을 제공한다.

                Returns:
                    Session: 요청 경계에서 닫는 실제 ORM 세션.
                """
                return orm_session

            context = ApplicationContext()
            context.add(request_engine)
            context.add(request_session)
            context.add(GitDirectoryObserver)
            context.add(ProjectRepository)
            context.add(SessionRepository)
            context.add(RegisterProjectUseCase)
            context.add(RegisterSessionUseCase)
            context.add(MoveSessionUseCase)
            context.add(GetSessionContextUseCase)
            context.start()
            try:
                yield context
            finally:
                context.stop()
                context.clear_context()
    finally:
        engine.dispose()

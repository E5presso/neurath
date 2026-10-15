"""독립적인 코어 요청의 Dishka 구성과 자원 수명을 관리한다."""

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from dishka import Container, Provider, Scope, from_context, make_container, provide
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from neurath.application.ports.repositories.project import IProjectRepository
from neurath.application.ports.repositories.session import ISessionRepository
from neurath.application.ports.services.directory_observer import IDirectoryObserver
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
    """짧게 유지하는 구성 컨테이너에 전달하는 불변 설정이다.

    Attributes:
        path: 명시적인 데이터베이스 경로이며 None이면 사용자 단위 기본 경로.
        write: 기존 데이터베이스에 쓰기를 허용할지 여부.
    """

    path: Path | None
    write: bool


class RequestProvider(Provider):
    """실제 생성자 주입과 프레임워크의 자원 정리 방식을 선언한다.

    Attributes:
        settings: 컨텍스트에서 전달하는 애플리케이션 범위의 저장 설정.
        observer: 요청 범위의 원시 디렉터리 관찰 어댑터.
        projects: 요청 범위의 프로젝트 저장소 구현.
        sessions: 요청 범위의 세션 저장소 구현.
        register_project: 요청 범위의 프로젝트 등록 유스케이스.
        register_session: 요청 범위의 네이티브 세션 등록 유스케이스.
        move_session: 요청 범위의 세션 이동 유스케이스.
        get_context: 요청 범위의 세션 컨텍스트 조회 유스케이스.
    """

    settings = from_context(provides=DatabaseSettings, scope=Scope.APP)
    observer = provide(GitDirectoryObserver, provides=IDirectoryObserver, scope=Scope.REQUEST)
    projects = provide(ProjectRepository, provides=IProjectRepository, scope=Scope.REQUEST)
    sessions = provide(SessionRepository, provides=ISessionRepository, scope=Scope.REQUEST)
    register_project = provide(RegisterProjectUseCase, scope=Scope.REQUEST)
    register_session = provide(RegisterSessionUseCase, scope=Scope.REQUEST)
    move_session = provide(MoveSessionUseCase, scope=Scope.REQUEST)
    get_context = provide(GetSessionContextUseCase, scope=Scope.REQUEST)

    @provide(scope=Scope.APP)
    def engine(self, settings: DatabaseSettings) -> Iterator[Engine]:
        """풀 없는 엔진을 생성하고 컨테이너가 닫힐 때 정리한다.

        Args:
            settings: 이 요청을 위한 불변 저장 설정.

        Yields:
            Engine: 요청한 SQLite 접근 모드로 제한한 엔진.
        """
        engine = create_database_engine(settings.path, write=settings.write)
        try:
            yield engine
        finally:
            engine.dispose()

    @provide(scope=Scope.REQUEST)
    def session(self, engine: Engine) -> Iterator[Session]:
        """하나의 ORM 세션을 제공하고 커밋 없이 항상 닫는다.

        트랜잭션 커밋과 롤백은 호출자의 Session.begin()이 소유한다.

        Args:
            engine: 상위 애플리케이션 범위에서 주입한 엔진.

        Yields:
            Session: 저장소들이 공유하는 요청 범위의 ORM 세션.
        """
        with Session(engine, expire_on_commit=False, close_resets_only=False) as session:
            yield session


def request_container(settings: DatabaseSettings) -> Container:
    """단일 호스트 요청을 위한 독립적인 구성 컨테이너를 만든다.

    Args:
        settings: 상주 실행 상태를 포함하지 않는 저장 경로와 접근 모드.

    Returns:
        Container: 요청 범위를 벗어난 뒤 호출자가 닫아야 하는 Dishka 컨테이너.
    """
    return make_container(RequestProvider(), context={DatabaseSettings: settings})

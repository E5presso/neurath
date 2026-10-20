"""명시적인 저장소 의존성으로 세션 이동을 구현한다."""

from dataclasses import dataclass

from spakky.core.stereotype.usecase import UseCase

from neurath.application.context import SessionContext
from neurath.application.ports.repositories.session import ISessionRepository
from neurath.application.usecases.register_project import RegisterProjectUseCase
from neurath.domain.errors import ContextNotFound
from neurath.domain.observations import DirectoryObservation


@dataclass(frozen=True)
class MoveSessionCommand:
    """단일 세션 이동 요청의 명시적 불변 입력이다.

    Attributes:
        project_id: 조회 대상 프로젝트의 안정적인 식별자.
        session_id: 지정한 프로젝트 안에 있는 세션의 식별자.
        observation: 프로젝트 식별 규칙에 사용하는 정규화된 외부 관찰 사실.
        expected_revision: 이동 요청 전에 관찰한 세션 버전.
    """

    project_id: str
    session_id: str
    observation: DirectoryObservation
    expected_revision: int


@UseCase()
class MoveSessionUseCase:
    """저장 수명을 소유하지 않고 프로젝트와 세션 규칙을 조정한다."""

    def __init__(self, projects: RegisterProjectUseCase, sessions: ISessionRepository) -> None:
        """단일 요청 트랜잭션에 속한 저장소를 주입받는다.

        Args:
            projects: 이 요청의 프로젝트 조회·등록 의존성.
            sessions: 이 요청의 세션 저장 포트.
        """
        self.projects = projects
        self.sessions = sessions

    def execute(self, request: MoveSessionCommand) -> SessionContext:
        """요청한 작업을 적용하고 분리된 불변 컨텍스트를 반환한다.

        Args:
            request: 요청 경계에서 전달한 명시적인 명령 또는 조회.

        Returns:
            SessionContext: 작업 후 프로젝트와 세션의 분리된 상태.

        Raises:
            ContextNotFound: 지정한 프로젝트 또는 세션이 요청한 범위에 없는 경우.
        """
        session = self.sessions.get(request.project_id, request.session_id)
        project = self.projects.execute(request.observation)
        if project.id != request.project_id:
            raise ContextNotFound("Working directory belongs to another project")
        session.move(request.observation.working_directory, request.expected_revision)
        session = self.sessions.save(session)
        return SessionContext.from_entities(project, session)

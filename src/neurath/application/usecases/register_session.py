"""명시적인 저장소 의존성으로 세션 등록을 구현한다."""

from dataclasses import dataclass
from typing import override

from spakky.core.stereotype.usecase import UseCase
from spakky.domain.application.command import AbstractCommand, ICommandUseCase

from neurath.application.dto.session import SessionDTO
from neurath.application.ports.repositories.session import ISessionRepository
from neurath.application.usecases.register_project import (
    RegisterProjectCommand,
    RegisterProjectUseCase,
)
from neurath.domain.aggregates.session import HostSession
from neurath.domain.observations import DirectoryObservation


@dataclass(frozen=True)
class RegisterSessionCommand(AbstractCommand):
    """단일 세션 등록 요청의 명시적 불변 입력이다.

    Attributes:
        observation: 프로젝트 식별 규칙에 사용하는 정규화된 외부 관찰 사실.
        provider: 네이티브 세션 식별자의 호스트 공급자 이름 공간.
        host_session_id: 호스트 공급자가 전달한 네이티브 세션 식별자.
    """

    observation: DirectoryObservation
    provider: str
    host_session_id: str


@UseCase()
class RegisterSessionUseCase(ICommandUseCase[RegisterSessionCommand, SessionDTO]):
    """저장 수명을 소유하지 않고 프로젝트와 세션 규칙을 조정한다."""

    def __init__(self, projects: RegisterProjectUseCase, sessions: ISessionRepository) -> None:
        """단일 요청 트랜잭션에 속한 저장소를 주입받는다.

        Args:
            projects: 이 요청의 프로젝트 조회·등록 의존성.
            sessions: 이 요청의 세션 저장 포트.
        """
        self.projects = projects
        self.sessions = sessions

    @override
    def run(self, command: RegisterSessionCommand) -> SessionDTO:
        """요청한 작업을 적용하고 분리된 불변 컨텍스트를 반환한다.

        Args:
            command: 요청 경계에서 전달한 명시적인 명령 또는 조회.

        Returns:
            SessionDTO: 작업 후 프로젝트와 세션의 분리된 상태.
        """
        project = self.projects.run(RegisterProjectCommand(command.observation))
        session = self.sessions.find(project.id, command.provider, command.host_session_id)
        if session is None:
            session = HostSession.create(
                project_id=project.id,
                provider=command.provider,
                host_session_id=command.host_session_id,
                working_directory=command.observation.working_directory,
            )
            session = self.sessions.save(session)
        return SessionDTO.from_entities(project, session)

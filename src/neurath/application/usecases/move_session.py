"""명시적인 저장소 의존성으로 세션 이동을 구현한다."""

from dataclasses import dataclass
from typing import override

from spakky.core.stereotype.usecase import UseCase
from spakky.domain.application.command import AbstractCommand, ICommandUseCase

from neurath.application.ports.repositories.session import ISessionRepository
from neurath.application.usecases.register_project import (
    RegisterProjectCommand,
    RegisterProjectUseCase,
)
from neurath.domain.aggregates.project import Project
from neurath.domain.aggregates.session import HostSession
from neurath.domain.observations import DirectoryObservation


@dataclass(frozen=True)
class MoveSessionCommand(AbstractCommand):
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


@dataclass(frozen=True)
class MoveSessionResult:
    """이 유스케이스의 처리 결과를 전달한다.

    Attributes:
        project: 요청한 프로젝트.
        session: 처리하거나 조회한 세션.
    """

    project: Project
    session: HostSession


@UseCase()
class MoveSessionUseCase(ICommandUseCase[MoveSessionCommand, MoveSessionResult]):
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
    def run(self, command: MoveSessionCommand) -> MoveSessionResult:
        """요청한 작업을 적용하고 분리된 처리 결과를 반환한다.

        Args:
            command: 요청 경계에서 전달한 명시적인 명령 또는 조회.

        Returns:
            MoveSessionResult: 처리 후 프로젝트와 세션.
        """
        session = self.sessions.get(command.session_id)
        session.require_project(command.project_id)
        project = self.projects.run(RegisterProjectCommand(command.observation)).project
        session.require_project(project.id)
        session.move(command.observation.working_directory, command.expected_revision)
        session = self.sessions.save(session)
        return MoveSessionResult(project=project, session=session)

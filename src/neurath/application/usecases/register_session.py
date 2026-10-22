"""프로젝트를 식별하고 공급자·네이티브 ID가 같은 세션을 재사용하거나 등록한다."""

from dataclasses import dataclass
from typing import override

from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.repositories.project import IProjectRepository
from neurath.application.ports.repositories.session import ISessionRepository
from neurath.domain.aggregates.project import Project
from neurath.domain.aggregates.session import HostSession
from neurath.domain.observations import DirectoryObservation


@dataclass(frozen=True)
class RegisterSessionCommand(AbstractCommand):
    """관찰한 프로젝트 위치와 등록할 호스트의 네이티브 세션 식별자를 지정한다.

    Attributes:
        observation: 프로젝트 식별 규칙에 사용하는 정규화된 외부 관찰 사실.
        provider: 네이티브 세션 식별자의 호스트 공급자 이름 공간.
        host_session_id: 호스트 공급자가 전달한 네이티브 세션 식별자.
    """

    observation: DirectoryObservation
    provider: str
    host_session_id: str


@dataclass(frozen=True)
class RegisterSessionResult:
    """등록 위치의 프로젝트와 기존 또는 새 호스트 세션을 반환한다.

    Attributes:
        project: 세션이 속한 프로젝트와 소유 위치.
        session: 동일 네이티브 ID의 기존 세션 또는 새로 생성한 세션.
    """

    project: Project
    session: HostSession


@UseCase()
class RegisterSessionUseCase(IAsyncCommandUseCase[RegisterSessionCommand, RegisterSessionResult]):
    """프로젝트를 식별하고 공급자·네이티브 ID가 같은 세션을 재사용하거나 등록한다.

    세션 키는 프로젝트·provider·host_session_id의 조합이다. 재등록 시 기존 세션의
    최근 작업 경로와 revision을 유지하며 경로 변경은 move_session에서 처리한다.
    """

    def __init__(
        self,
        projects: IProjectRepository,
        sessions: ISessionRepository,
    ) -> None:
        """위치 식별 유스케이스와 네이티브 세션 저장소를 받는다.

        Args:
            projects: 관찰한 위치를 RegisterProjectUseCase로 식별·등록한다.
            sessions: 프로젝트·공급자·네이티브 ID로 세션을 찾고 없을 때 새 세션을 저장한다.
        """
        self.projects = projects
        self.sessions = sessions

    @transactional
    @override
    async def run(self, command: RegisterSessionCommand) -> RegisterSessionResult:
        """프로젝트를 등록·조회한 뒤 동일한 네이티브 세션을 재사용하거나 새로 저장한다.

        Args:
            command: 프로젝트 위치 관찰과 공급자·네이티브 세션 ID.

        Returns:
            RegisterSessionResult: 관찰한 위치의 프로젝트와 재사용하거나 생성한 호스트 세션.
        """
        candidates = Project.identify(command.observation)
        owners = []
        for location in candidates:
            owner = await self.projects.find_by_location(location)
            if owner is not None:
                owners.append(owner)
        project = Project.owner_of(owners)
        if project is None:
            project = Project.create(command.observation)
        project.associate(candidates)
        project = await self.projects.save(project)
        session = await self.sessions.find_by_project_id_and_provider_and_host_session_id(
            project.id, command.provider, command.host_session_id
        )
        if session is None:
            session = HostSession.create(
                project_id=project.id,
                provider=command.provider,
                host_session_id=command.host_session_id,
                working_directory=command.observation.working_directory,
            )
            session = await self.sessions.save(session)
        return RegisterSessionResult(project=project, session=session)

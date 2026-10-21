"""세션의 프로젝트를 유지한 채 관찰된 작업 디렉터리로 이동한다."""

from dataclasses import dataclass
from typing import override

from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase
from spakky.plugins.sqlalchemy.persistency.session_manager import AsyncSessionManager
from sqlalchemy import select

from neurath.application.ports.repositories.project import IProjectRepository
from neurath.application.ports.repositories.session import ISessionRepository
from neurath.domain.aggregates.project import Project
from neurath.domain.aggregates.session import HostSession
from neurath.domain.observations import DirectoryObservation
from neurath.infrastructure.models.project import ProjectLocationModel, ProjectModel


@dataclass(frozen=True)
class MoveSessionCommand(AbstractCommand):
    """세션을 이동할 디렉터리 관찰과 현재 프로젝트·저장 revision을 지정한다.

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
    """동일 프로젝트와 이동 후 작업 경로를 가진 세션을 반환한다.

    Attributes:
        project: 세션이 속한 프로젝트와 소유 위치.
        session: 이동 후 작업 경로와 저장 revision을 가진 세션.
    """

    project: Project
    session: HostSession


@UseCase()
class MoveSessionUseCase(IAsyncCommandUseCase[MoveSessionCommand, MoveSessionResult]):
    """세션의 프로젝트를 유지한 채 관찰된 작업 디렉터리로 이동한다.

    이동 목적지의 프로젝트를 식별하고 기존 프로젝트와 같을 때만 경로를 변경한다.
    다른 프로젝트는 ContextNotFound, 오래된 세션 revision은 RevisionConflict로 거부한다.
    같은 경로로 이동하면 변경 토큰과 revision은 유지한다.
    """

    def __init__(
        self,
        session_manager: AsyncSessionManager,
        projects: IProjectRepository,
        sessions: ISessionRepository,
    ) -> None:
        """목적지 프로젝트 식별과 세션 경로 저장에 필요한 의존성을 받는다.

        Args:
            session_manager: 조건 조회를 현재 트랜잭션의 SQLAlchemy 세션으로 수행한다.
            projects: 목적지 관찰을 소유 위치로 식별하여 기존 프로젝트와 대조한다.
            sessions: 이동할 세션을 조회하고 같은 프로젝트의 새 작업 경로를 저장한다.
        """
        self.session_manager = session_manager
        self.projects = projects
        self.sessions = sessions

    @transactional
    @override
    async def run(self, command: MoveSessionCommand) -> MoveSessionResult:
        """목적지의 프로젝트와 세션 revision을 확인하고 작업 경로 변경을 저장한다.

        Args:
            command: 현재 프로젝트·세션, 이동 목적지 관찰과 읽은 세션 revision.

        Returns:
            MoveSessionResult: 프로젝트와 이동한 세션. 같은 경로이면 기존 상태를 유지한다.
        """
        session = await self.sessions.get(command.session_id)
        session.require_project(command.project_id)
        candidates = Project.identify(command.observation)
        owners = []
        for location in candidates:
            owner = (
                await self.projects.get(found_id)
                if (
                    found_id := await self.session_manager.session.scalar(
                        select(ProjectModel.id)
                        .join(ProjectModel.locations)
                        .where(
                            ProjectLocationModel.kind == location.kind.value,
                            ProjectLocationModel.path == location.path,
                        )
                    )
                )
                is not None
                else None
            )
            if owner is not None:
                owners.append(owner)
        project = Project.owner_of(owners)
        if project is None:
            project = Project.create(command.observation)
        project.associate(candidates)
        project = await self.projects.save(project)
        session.require_project(project.id)
        session.move(command.observation.working_directory, command.expected_revision)
        session = await self.sessions.save(session)
        return MoveSessionResult(project=project, session=session)

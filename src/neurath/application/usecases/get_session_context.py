"""세션의 프로젝트 소속을 확인하고 프로젝트·세션을 함께 조회한다."""

from dataclasses import dataclass
from typing import override

from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.query import AbstractQuery, IAsyncQueryUseCase

from neurath.application.ports.repositories.project import IProjectRepository
from neurath.application.ports.repositories.session import ISessionRepository
from neurath.domain.aggregates.project import Project
from neurath.domain.aggregates.session import HostSession


@dataclass(frozen=True)
class GetSessionContextQuery(AbstractQuery):
    """현재 작업 경로와 프로젝트를 조회할 세션을 지정한다.

    Attributes:
        project_id: 조회 대상 프로젝트의 안정적인 식별자.
        session_id: 지정한 프로젝트 안에 있는 세션의 식별자.
    """

    project_id: str
    session_id: str


@dataclass(frozen=True)
class GetSessionContextResult:
    """조회한 프로젝트와 해당 프로젝트에 속한 호스트 세션을 반환한다.

    Attributes:
        project: 세션이 속한 프로젝트와 소유 위치.
        session: 저장된 작업 경로와 revision을 가진 조회 세션.
    """

    project: Project
    session: HostSession


@UseCase()
class GetSessionContextUseCase(IAsyncQueryUseCase[GetSessionContextQuery, GetSessionContextResult]):
    """세션의 프로젝트 소속을 확인하고 프로젝트·세션을 함께 조회한다.

    저장된 작업 경로와 revision을 읽으며 새 등록·위치 관찰·경로 변경을 수행하지 않는다.
    다른 프로젝트의 세션을 지정하면 ContextNotFound가 발생한다.
    """

    def __init__(self, projects: IProjectRepository, sessions: ISessionRepository) -> None:
        """프로젝트와 세션을 함께 조회할 저장소를 받는다.

        Args:
            projects: 세션이 속한 프로젝트의 위치·식별 정보를 조회한다.
            sessions: 세션의 프로젝트 소속·작업 경로·revision을 조회한다.
        """
        self.projects = projects
        self.sessions = sessions

    @transactional
    @override
    async def run(self, query: GetSessionContextQuery) -> GetSessionContextResult:
        """프로젝트 소속을 확인한 세션과 해당 프로젝트를 변경 없이 반환한다.

        Args:
            query: 조회할 세션 ID와 그 세션이 속해야 하는 프로젝트 ID.

        Returns:
            GetSessionContextResult: 저장된 프로젝트와 작업 경로·revision을 가진 세션.
        """
        session = await self.sessions.get(query.session_id)
        session.require_project(query.project_id)
        project = await self.projects.get(query.project_id)
        return GetSessionContextResult(project=project, session=session)

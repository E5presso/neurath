"""명시적인 저장소 의존성으로 세션 컨텍스트 조회를 구현한다."""

from dataclasses import dataclass
from typing import override

from spakky.core.stereotype.usecase import UseCase
from spakky.domain.application.query import AbstractQuery, IQueryUseCase

from neurath.application.ports.repositories.project import IProjectRepository
from neurath.application.ports.repositories.session import ISessionRepository
from neurath.domain.aggregates.project import Project
from neurath.domain.aggregates.session import HostSession


@dataclass(frozen=True)
class GetSessionContextQuery(AbstractQuery):
    """단일 세션 컨텍스트 조회 요청의 명시적 불변 입력이다.

    Attributes:
        project_id: 조회 대상 프로젝트의 안정적인 식별자.
        session_id: 지정한 프로젝트 안에 있는 세션의 식별자.
    """

    project_id: str
    session_id: str


@dataclass(frozen=True)
class GetSessionContextResult:
    """이 유스케이스의 처리 결과를 전달한다.

    Attributes:
        project: 요청한 프로젝트.
        session: 처리하거나 조회한 세션.
    """

    project: Project
    session: HostSession


@UseCase()
class GetSessionContextUseCase(IQueryUseCase[GetSessionContextQuery, GetSessionContextResult]):
    """저장 수명을 소유하지 않고 프로젝트와 세션 규칙을 조정한다."""

    def __init__(self, projects: IProjectRepository, sessions: ISessionRepository) -> None:
        """단일 요청 트랜잭션에 속한 저장소를 주입받는다.

        Args:
            projects: 이 요청의 프로젝트 조회·등록 의존성.
            sessions: 이 요청의 세션 저장 포트.
        """
        self.projects = projects
        self.sessions = sessions

    @override
    def run(self, query: GetSessionContextQuery) -> GetSessionContextResult:
        """요청한 작업을 적용하고 분리된 처리 결과를 반환한다.

        Args:
            query: 요청 경계에서 전달한 명시적인 명령 또는 조회.

        Returns:
            GetSessionContextResult: 처리 후 프로젝트와 세션.
        """
        session = self.sessions.get(query.session_id)
        session.require_project(query.project_id)
        project = self.projects.get(query.project_id)
        return GetSessionContextResult(project=project, session=session)

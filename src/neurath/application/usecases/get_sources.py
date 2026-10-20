"""GetSources 요청의 조회·도메인 판단·저장 순서를 조정한다."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import override

from spakky.core.stereotype.usecase import UseCase
from spakky.domain.application.query import AbstractQuery, IQueryUseCase

from neurath.application.ports.repositories.request_source import IRequestSourceRepository
from neurath.application.ports.repositories.session import ISessionRepository
from neurath.domain.aggregates.request_source import RequestSource


@dataclass(frozen=True)
class GetSourcesQuery(AbstractQuery):
    """요청 범위와 명시적인 입력이다.

    Attributes:
        project_id: 요청 프로젝트.
        session_id: 현재 세션.
    """

    project_id: str
    session_id: str


@dataclass(frozen=True)
class GetSourcesResult:
    """이 유스케이스의 처리 결과를 전달한다.

    Attributes:
        sources: 프로젝트에 보존한 원문과 정정 계보.
    """

    sources: Sequence[RequestSource]


@UseCase()
class GetSourcesUseCase(IQueryUseCase[GetSourcesQuery, GetSourcesResult]):
    """프레임워크 저장 계약으로 한 요청의 도메인 동작을 조정한다."""

    def __init__(self, sessions: ISessionRepository, sources: IRequestSourceRepository) -> None:
        """현재 요청의 저장소를 주입받는다.

        Args:
            sessions: 요청에 속하는 sessions 저장소.
            sources: 요청에 속하는 sources 저장소.
        """
        self.sessions = sessions
        self.sources = sources

    @override
    def run(self, query: GetSourcesQuery) -> GetSourcesResult:
        """명시한 요청을 적용하고 결과를 반환한다.

        Args:
            query: 원문·범위·관찰에 연결된 입력.

        Returns:
            GetSourcesResult: 처리한 원장과 현재 상태.
        """
        self.sessions.get(query.session_id).require_project(query.project_id)
        return GetSourcesResult(sources=self.sources.list(query.project_id))

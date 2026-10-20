"""GetSources 요청의 조회·도메인 판단·저장 순서를 조정한다."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import override

from spakky.core.stereotype.usecase import UseCase
from spakky.domain.application.query import AbstractQuery, IQueryUseCase

from neurath.application.dto.task import SourceDTO
from neurath.application.ports.repositories.request_source import IRequestSourceRepository
from neurath.application.ports.repositories.session import ISessionRepository


@dataclass(frozen=True)
class GetSourcesQuery(AbstractQuery):
    """요청 범위와 명시적인 입력이다.

    Attributes:
        project_id: 요청 프로젝트.
        session_id: 현재 세션.
    """

    project_id: str
    session_id: str


@UseCase()
class GetSourcesUseCase(IQueryUseCase[GetSourcesQuery, Sequence[SourceDTO]]):
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
    def run(self, query: GetSourcesQuery) -> Sequence[SourceDTO]:
        """명시한 요청을 적용하고 불변 결과를 반환한다.

        Args:
            query: 원문·범위·관찰에 연결된 입력.

        Returns:
            Sequence[SourceDTO]: 현재 상태를 나타내는 불변 결과.
        """
        self.sessions.get(query.session_id).require_project(query.project_id)
        return tuple(
            SourceDTO.from_entity(source) for source in self.sources.list(query.project_id)
        )

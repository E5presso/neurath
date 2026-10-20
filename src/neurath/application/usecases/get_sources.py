"""호출 세션의 프로젝트를 확인한 뒤 프로젝트 전체 출처를 조회한다."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import override

from spakky.core.pod.annotations.pod import Pod
from spakky.core.stereotype.usecase import UseCase
from spakky.domain.application.query import AbstractQuery, IAsyncQueryUseCase

from neurath.application.ports.repositories.request_source import IRequestSourceRepository
from neurath.application.ports.repositories.session import ISessionRepository
from neurath.domain.aggregates.request_source import RequestSource


@dataclass(frozen=True)
class GetSourcesQuery(AbstractQuery):
    """원문 목록을 조회할 프로젝트와 그 프로젝트에 속한 호출 세션을 지정한다.

    Attributes:
        project_id: 원문을 조회하거나 기록할 프로젝트 ID.
        session_id: 해당 프로젝트에 속한 호출 세션 ID.
    """

    project_id: str
    session_id: str


@dataclass(frozen=True)
class GetSourcesResult:
    """프로젝트의 원문·정정·상태 질문·요약 기록을 모두 반환한다.

    Attributes:
        sources: 최초 세션에 관계없이 조회한 프로젝트의 전체 출처. 빈 경우 빈 Sequence.
    """

    sources: Sequence[RequestSource]


@UseCase(scope=Pod.Scope.CONTEXT)
class GetSourcesUseCase(IAsyncQueryUseCase[GetSourcesQuery, GetSourcesResult]):
    """호출 세션의 프로젝트를 확인한 뒤 프로젝트 전체 출처를 조회한다.

    다른 세션이 기록한 출처도 포함하므로 기존 원문을 재사용하고 정정 계보를
    찾을 수 있다. 정정 관계는 각 출처의 corrects_id에 남으며 새 요구를 만들지 않는다.
    """

    def __init__(self, sessions: ISessionRepository, sources: IRequestSourceRepository) -> None:
        """호출 세션의 범위와 프로젝트 원문 목록을 읽을 저장소를 받는다.

        Args:
            sessions: 호출 세션의 프로젝트 소속을 확인한다.
            sources: 기록한 세션에 관계없이 프로젝트의 모든 출처를 조회한다.
        """
        self.sessions = sessions
        self.sources = sources

    @override
    async def run(self, query: GetSourcesQuery) -> GetSourcesResult:
        """세션의 프로젝트 소속을 확인하고 해당 프로젝트의 모든 출처를 반환한다.

        Args:
            query: 출처를 조회할 프로젝트 ID와 해당 프로젝트에 속한 세션 ID.

        Returns:
            GetSourcesResult: 최초 기록 세션에 관계없이 프로젝트에 보존된 출처 목록.
        """
        (await self.sessions.get(query.session_id)).require_project(query.project_id)
        return GetSourcesResult(sources=(await self.sources.list(query.project_id)))

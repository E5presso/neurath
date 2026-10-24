"""보존 자료의 실제 등록 위치와 재개 연결을 읽는다."""

from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.query import AbstractQuery, IAsyncQueryUseCase
from spakky.plugins.sqlalchemy.persistency.session_manager import AsyncSessionManager

from neurath.domain.aggregates.historical_archive import HistoricalArchive
from neurath.domain.errors import ContextNotFound
from neurath.infrastructure.models.historical_archive import HistoricalArchiveModel


@immutable
class GetHistoricalArchiveQuery(AbstractQuery):
    """조회할 보존 자료를 지정한다.

    Attributes:
        archive_id: 등록된 자료 식별자.
    """

    archive_id: UUID


@UseCase()
class GetHistoricalArchiveUseCase(IAsyncQueryUseCase[GetHistoricalArchiveQuery, HistoricalArchive]):
    """과거 신원에 현재 실행을 연결하지 않는 읽기다."""

    def __init__(self, sessions: AsyncSessionManager) -> None:
        """읽기 전용 SQLAlchemy 세션을 받는다.

        Args:
            sessions: 현재 읽기 트랜잭션.
        """
        self.sessions = sessions

    @transactional
    @override
    async def run(self, query: GetHistoricalArchiveQuery) -> HistoricalArchive:
        """등록된 사본 정보와 실제 재개 연결만 반환한다.

        Args:
            query: 선택한 자료.

        Returns:
            HistoricalArchive: 보존 자료와 현재 작업 참조.

        Raises:
            ContextNotFound: 등록된 자료가 없는 경우.
        """
        row = await self.sessions.session.get(HistoricalArchiveModel, query.archive_id)
        if row is None:
            raise ContextNotFound("Historical archive does not exist")
        return row.to_domain()

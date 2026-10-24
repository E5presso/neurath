"""복구 기록을 변경하지 않고 기존 장애 목록의 선택 범위를 읽는다."""

from collections.abc import Sequence
from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.query import AbstractQuery, IAsyncQueryUseCase
from spakky.plugins.sqlalchemy.persistency.session_manager import AsyncSessionManager
from sqlalchemy import select

from neurath.domain.aggregates.incident import Incident
from neurath.infrastructure.models.incident import IncidentModel


@immutable
class ListIncidentsQuery(AbstractQuery):
    """동일 원장의 다음 페이지를 선택한다.

    Attributes:
        after_id: 이전 페이지의 마지막 사건 ID.
        limit: 이번 조회의 최대 개수.
    """

    after_id: UUID | None = None
    limit: int = 20


@UseCase()
class ListIncidentsUseCase(IAsyncQueryUseCase[ListIncidentsQuery, Sequence[Incident]]):
    """원 증상과 현재 처리 상태를 읽으며 journal을 가져오거나 해결하지 않는다."""

    def __init__(self, sessions: AsyncSessionManager) -> None:
        """현재 조회의 실제 SQLAlchemy 세션을 받는다.

        Args:
            sessions: 읽기 전용 조회 범위의 세션.
        """
        self.sessions = sessions

    @transactional
    @override
    async def run(self, query: ListIncidentsQuery) -> Sequence[Incident]:
        """ID 순서로 제한한 장애와 그 근거를 반환한다.

        Args:
            query: 페이지 범위.

        Returns:
            Sequence[Incident]: 현재 상태를 변경하지 않은 사건들.

        Raises:
            ValueError: 지원하는 페이지 크기를 벗어난 경우.
        """
        if not 1 <= query.limit <= 100:
            raise ValueError("Incident limit must be between 1 and 100")
        statement = select(IncidentModel).order_by(IncidentModel.id).limit(query.limit)
        if query.after_id is not None:
            statement = statement.where(IncidentModel.id > query.after_id)
        rows = await self.sessions.session.scalars(statement)
        return tuple(row.to_domain() for row in rows)

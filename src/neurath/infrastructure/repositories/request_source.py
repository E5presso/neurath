"""원문과 정정 출처의 기본 Aggregate 저장 계약을 제공한다."""

from collections.abc import Sequence
from typing import override
from uuid import UUID

from spakky.data.stereotype.repository import Repository
from spakky.plugins.sqlalchemy.persistency.repository import AbstractAsyncGenericRepository
from sqlalchemy import select

from neurath.application.ports.repositories.request_source import IRequestSourceRepository
from neurath.domain.aggregates.request_source import RequestSource
from neurath.infrastructure.models.request_source import RequestSourceModel


@Repository()
class SQLAlchemyRequestSourceRepository(
    AbstractAsyncGenericRepository[RequestSource, UUID], IRequestSourceRepository
):
    """원래 작성자와 정정 관계를 보존하는 원문를 표준 SQLAlchemy 매핑·CRUD·낙관적 잠금으로 저장한다."""

    @override
    async def find_by_session_id(self, session_id: UUID) -> Sequence[RequestSource]:
        """태스크에 연결되지 않은 지시도 작성 순서대로 반환한다.

        Args:
            session_id: 조회할 원문 소유 세션.

        Returns:
            Sequence[RequestSource]: 출처와 정정 이력이 유지된 원문 목록.
        """
        rows = await self._session_manager.session.scalars(
            select(RequestSourceModel)
            .where(RequestSourceModel.session_id == session_id)
            .order_by(RequestSourceModel.created_at, RequestSourceModel.id)
        )
        return tuple(row.to_domain() for row in rows)

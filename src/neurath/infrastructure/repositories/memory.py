"""Memory의 선언형 매핑에 프레임워크 기본 CRUD를 연결한다."""

from collections.abc import Sequence
from typing import override
from uuid import UUID

from spakky.data.stereotype.repository import Repository
from spakky.plugins.sqlalchemy.persistency.repository import AbstractAsyncGenericRepository
from sqlalchemy import select

from neurath.application.ports.repositories.memory import IMemoryRepository
from neurath.domain.aggregates.memory import Memory, MemoryKind
from neurath.infrastructure.models.memory import MemoryModel


@Repository()
class SQLAlchemyMemoryRepository(AbstractAsyncGenericRepository[Memory, UUID], IMemoryRepository):
    """Memory aggregate를 기본 저장 계약으로 읽고 쓴다."""

    @override
    async def find_by_project_id_and_kind(
        self, project_id: UUID, kind: MemoryKind
    ) -> Sequence[Memory]:
        """기억 유형과 프로젝트를 실제 저장 조건으로 대조한다.

        Args:
            project_id: 현재 프로젝트.
            kind: 조회할 기억 유형.

        Returns:
            Sequence[Memory]: 원래 출처와 상태 이력을 가진 기록.
        """
        rows = await self._session_manager.session.scalars(
            select(MemoryModel)
            .where(MemoryModel.project_id == project_id, MemoryModel.kind == kind.value)
            .order_by(MemoryModel.created_at, MemoryModel.id)
        )
        return tuple(row.to_domain() for row in rows)

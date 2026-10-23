"""Delegation을 프레임워크 CRUD와 낙관적 잠금으로 저장한다."""

from collections.abc import Sequence
from typing import override
from uuid import UUID

from spakky.data.stereotype.repository import Repository
from spakky.plugins.sqlalchemy.persistency.repository import AbstractAsyncGenericRepository
from sqlalchemy import select

from neurath.application.ports.repositories.delegation import IDelegationRepository
from neurath.domain.aggregates.delegation import Delegation
from neurath.infrastructure.models.delegation import DelegationModel


@Repository()
class SQLAlchemyDelegationRepository(
    AbstractAsyncGenericRepository[Delegation, UUID], IDelegationRepository
):
    """Delegation의 조회·매핑을 담당하며 상태 판단은 도메인에 맡긴다."""

    @override
    async def find_by_task_id(self, task_id: UUID) -> Sequence[Delegation]:
        """조건에 해당하는 aggregate를 조회한다.

        Args:
            task_id: 조회할 task_id 범위.

        Returns:
            Sequence[Delegation]: 현재 저장된 대상이며 없으면 빈 결과.
        """
        rows = await self._session_manager.session.scalars(
            select(DelegationModel).where(DelegationModel.task_id == task_id)
        )
        return tuple(row.to_domain() for row in rows)

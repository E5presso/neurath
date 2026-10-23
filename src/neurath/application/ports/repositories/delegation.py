"""Delegation aggregate의 저장·범위 조회 계약이다."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from uuid import UUID

from spakky.data.persistency.repository import IAsyncGenericRepository

from neurath.domain.aggregates.delegation import Delegation


class IDelegationRepository(IAsyncGenericRepository[Delegation, UUID], ABC):
    """Delegation의 기본 CRUD와 배정 범위 조회를 제공한다."""

    @abstractmethod
    async def find_by_task_id(self, task_id: UUID) -> Sequence[Delegation]:
        """조건에 해당하는 aggregate를 조회한다.

        Args:
            task_id: 조회할 task_id 범위.

        Returns:
            Sequence[Delegation]: 현재 저장된 대상이며 없으면 빈 결과.

        Raises:
            NotImplementedError: 저장·실행 어댑터가 이 계약을 구현하지 않은 경우.
        """
        raise NotImplementedError

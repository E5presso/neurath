"""Memory aggregate의 프레임워크 저장 계약이다."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from uuid import UUID

from spakky.data.persistency.repository import IAsyncGenericRepository

from neurath.domain.aggregates.memory import Memory, MemoryKind


class IMemoryRepository(IAsyncGenericRepository[Memory, UUID], ABC):
    """Memory의 기본 저장·식별자 조회를 상속한다."""

    @abstractmethod
    async def find_by_project_id_and_kind(
        self, project_id: UUID, kind: MemoryKind
    ) -> Sequence[Memory]:
        """같은 프로젝트의 관련 유형 기억을 조회한다.

        Args:
            project_id: 현재 작업 프로젝트.
            kind: 조회할 기억 유형.

        Returns:
            Sequence[Memory]: 현재 프로젝트에 저장된 해당 유형의 기록.

        Raises:
            NotImplementedError: 구현되지 않은 계약을 호출한 경우.
        """
        raise NotImplementedError

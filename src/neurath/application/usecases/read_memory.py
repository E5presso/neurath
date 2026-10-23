"""선택한 과거 기억을 현재 사실로 승격하지 않고 원문 그대로 조회한다."""

from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.query import AbstractQuery, IAsyncQueryUseCase

from neurath.application.ports.repositories.memory import IMemoryRepository
from neurath.domain.aggregates.memory import Memory
from neurath.domain.errors import ContextNotFound


@immutable
class ReadMemoryQuery(AbstractQuery):
    """선택 조회할 기록과 프로젝트를 지정한다.

    Attributes:
        project_id: 허용된 조회 범위.
        memory_id: 검색 또는 참조에서 선택한 기억 ID.
    """

    project_id: UUID
    memory_id: UUID


@UseCase()
class ReadMemoryUseCase(IAsyncQueryUseCase[ReadMemoryQuery, Memory]):
    """과거 본문·출처를 반환하며 현재 맥락과 소유권은 변경하지 않는다."""

    def __init__(self, memories: IMemoryRepository) -> None:
        """기억 조회 저장소를 받는다.

        Args:
            memories: 선택한 기록의 기본 식별자 조회.
        """
        self.memories = memories

    @transactional
    @override
    async def run(self, query: ReadMemoryQuery) -> Memory:
        """프로젝트 범위를 확인한 뒤 원래 기록을 반환한다.

        Args:
            query: 프로젝트와 기록 ID.

        Returns:
            Memory: 본문을 자르지 않은 과거 기록.

        Raises:
            ContextNotFound: 다른 프로젝트의 기록인 경우.
        """
        memory = await self.memories.get(query.memory_id)
        if memory.project_id != query.project_id:
            raise ContextNotFound("Memory belongs to another project")
        return memory

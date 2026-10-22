"""Memory aggregate의 프레임워크 저장 계약이다."""

from abc import ABC

from spakky.data.persistency.repository import IAsyncGenericRepository

from neurath.domain.aggregates.memory import Memory


class IMemoryRepository(IAsyncGenericRepository[Memory, str], ABC):
    """Memory의 기본 저장·식별자 조회를 상속한다."""

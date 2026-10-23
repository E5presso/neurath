"""기사가 소유하는 모든 이력의 저장과 명령 범위 조회 계약이다."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from uuid import UUID

from spakky.data.persistency.repository import IAsyncGenericRepository

from neurath.domain.aggregates.article import Article


class IArticleRepository(IAsyncGenericRepository[Article, UUID], ABC):
    """기본 CRUD와 수신 훅에 필요한 기사 범위 조회를 제공한다."""

    @abstractmethod
    async def find_by_recipient_id(self, peer_id: UUID) -> Sequence[Article]:
        """아직 소비하지 않은 알림의 원 기사를 조회한다.

        Args:
            peer_id: 현재 훅의 관찰한 피어.

        Returns:
            Sequence[Article]: 미소비 알림을 소유한 기사.

        Raises:
            NotImplementedError: 저장 어댑터가 계약을 구현하지 않은 경우.
        """
        raise NotImplementedError

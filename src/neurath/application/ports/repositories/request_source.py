"""원문과 정정 출처의 기본 Aggregate 저장 계약을 제공한다."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from uuid import UUID

from spakky.data.persistency.repository import IAsyncGenericRepository

from neurath.domain.aggregates.request_source import RequestSource


class IRequestSourceRepository(IAsyncGenericRepository[RequestSource, UUID], ABC):
    """원래 작성자와 정정 관계를 보존하는 원문의 식별자 조회와 저장을 프레임워크 기본 계약으로 제공한다."""

    @abstractmethod
    async def find_by_session_id(self, session_id: UUID) -> Sequence[RequestSource]:
        """TODO 생성 여부와 관계없이 세션의 원문을 조회한다.

        Args:
            session_id: 원문을 처음 받은 세션.

        Returns:
            Sequence[RequestSource]: 정정과 미분류 지시를 포함한 저장 원문.

        Raises:
            NotImplementedError: 추상 계약을 구현하지 않은 경우.
        """
        raise NotImplementedError

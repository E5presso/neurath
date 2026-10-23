"""Enclave aggregate의 프레임워크 저장 계약이다."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from uuid import UUID

from spakky.data.persistency.repository import IAsyncGenericRepository

from neurath.domain.aggregates.enclave import Enclave


class IEnclaveRepository(IAsyncGenericRepository[Enclave, UUID], ABC):
    """Enclave의 기본 저장·식별자 조회를 상속한다."""

    @abstractmethod
    async def find_by_session_id(self, session_id: UUID) -> Sequence[Enclave]:
        """세션에 속한 현재 맥락 aggregate들을 조회한다.

        Args:
            session_id: 소유 세션의 내부 ID.

        Returns:
            Sequence[Enclave]: 작업별 범위를 포함하는 enclave 목록.

        Raises:
            NotImplementedError: 구현체가 추상 본문을 호출한 경우.
        """
        raise NotImplementedError

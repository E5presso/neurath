"""Message aggregate의 저장·범위 조회 계약이다."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from uuid import UUID

from spakky.data.persistency.repository import IAsyncGenericRepository

from neurath.domain.aggregates.message import Message


class IMessageRepository(IAsyncGenericRepository[Message, UUID], ABC):
    """Message의 기본 CRUD와 배정 범위 조회를 제공한다."""

    @abstractmethod
    async def find_by_sender_id_and_recipient_id_and_key(
        self, sender_id: UUID, recipient_id: UUID, key: str
    ) -> Message | None:
        """조건에 해당하는 aggregate를 조회한다.

        Args:
            sender_id: 조회할 sender_id 범위.
            recipient_id: 조회할 recipient_id 범위.
            key: 조회할 key 범위.

        Returns:
            Message | None: 현재 저장된 대상이며 없으면 빈 결과.

        Raises:
            NotImplementedError: 저장·실행 어댑터가 이 계약을 구현하지 않은 경우.
        """
        raise NotImplementedError

    @abstractmethod
    async def find_by_recipient_id(self, recipient_id: UUID) -> Sequence[Message]:
        """조건에 해당하는 aggregate를 조회한다.

        Args:
            recipient_id: 조회할 recipient_id 범위.

        Returns:
            Sequence[Message]: 현재 저장된 대상이며 없으면 빈 결과.

        Raises:
            NotImplementedError: 저장·실행 어댑터가 이 계약을 구현하지 않은 경우.
        """
        raise NotImplementedError

    @abstractmethod
    async def find_by_sender_id_and_key(self, sender_id: UUID, key: str) -> Sequence[Message]:
        """같은 발행의 원 수신 목록을 조회한다.

        Args:
            sender_id: 원 발신 피어.
            key: 재시도에서 재사용한 발행 키.

        Returns:
            Sequence[Message]: 최초 발행에서 확정한 메시지들.

        Raises:
            NotImplementedError: 저장 어댑터가 계약을 구현하지 않은 경우.
        """
        raise NotImplementedError

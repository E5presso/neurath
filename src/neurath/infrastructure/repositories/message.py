"""Message을 프레임워크 CRUD와 낙관적 잠금으로 저장한다."""

from collections.abc import Sequence
from typing import override

from spakky.data.stereotype.repository import Repository
from spakky.plugins.sqlalchemy.persistency.repository import AbstractAsyncGenericRepository
from sqlalchemy import select

from neurath.application.ports.repositories.message import IMessageRepository
from neurath.domain.aggregates.message import Message
from neurath.infrastructure.models.message import MessageModel


@Repository()
class SQLAlchemyMessageRepository(AbstractAsyncGenericRepository[Message, str], IMessageRepository):
    """Message의 조회·매핑을 담당하며 상태 판단은 도메인에 맡긴다."""

    @override
    async def find_by_sender_id_and_recipient_id_and_key(
        self, sender_id: str, recipient_id: str, key: str
    ) -> Message | None:
        """조건에 해당하는 aggregate를 조회한다.

        Args:
            sender_id: 조회할 sender_id 범위.
            recipient_id: 조회할 recipient_id 범위.
            key: 조회할 key 범위.

        Returns:
            Message | None: 현재 저장된 대상이며 없으면 빈 결과.
        """
        rows = await self._session_manager.session.scalar(
            select(MessageModel).where(
                MessageModel.sender_id == sender_id,
                MessageModel.recipient_id == recipient_id,
                MessageModel.key == key,
            )
        )
        if rows is None:
            return None
        return rows.to_domain()

    @override
    async def find_by_recipient_id(self, recipient_id: str) -> Sequence[Message]:
        """조건에 해당하는 aggregate를 조회한다.

        Args:
            recipient_id: 조회할 recipient_id 범위.

        Returns:
            Sequence[Message]: 현재 저장된 대상이며 없으면 빈 결과.
        """
        rows = await self._session_manager.session.scalars(
            select(MessageModel).where(MessageModel.recipient_id == recipient_id)
        )
        return tuple(row.to_domain() for row in rows)

    @override
    async def find_by_sender_id_and_key(self, sender_id: str, key: str) -> Sequence[Message]:
        """이미 확정한 발행 수신자를 재조회한다.

        Args:
            sender_id: 원 발신 피어.
            key: 동일 발행 키.

        Returns:
            Sequence[Message]: 기존 수신자와 원문을 보존한 메시지들.
        """
        rows = await self._session_manager.session.scalars(
            select(MessageModel).where(MessageModel.sender_id == sender_id, MessageModel.key == key)
        )
        return tuple(row.to_domain() for row in rows)

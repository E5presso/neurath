"""원 수신자에게 전체 본문을 반환하며 출력 전에는 읽음을 기록하지 않는다."""

from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.query import AbstractQuery, IAsyncQueryUseCase

from neurath.application.ports.repositories.message import IMessageRepository
from neurath.domain.aggregates.message import Message


@immutable
class ReadMessageQuery(AbstractQuery):
    """원 수신자에게 전체 본문을 반환하며 출력 전에는 읽음을 기록하지 않는다.

    Attributes:
        message_id: 선택한 원 메시지 ID.
        peer_id: 호출한 등록 피어.
    """

    message_id: UUID
    peer_id: UUID


@UseCase()
class ReadMessageUseCase(IAsyncQueryUseCase[ReadMessageQuery, Message]):
    """원 수신자에게 전체 본문을 반환하며 출력 전에는 읽음을 기록하지 않는다."""

    def __init__(self, messages: IMessageRepository) -> None:
        """요청 범위의 조회·저장 계약을 받는다.

        Args:
            messages: Message aggregate의 범위 조회와 저장.
        """
        self.messages = messages

    @transactional
    @override
    async def run(self, query: ReadMessageQuery) -> Message:
        """원 수신자에게 전체 본문을 반환하며 출력 전에는 읽음을 기록하지 않는다.

        Args:
            query: 원문·수신 범위와 해당 작업에 필요한 입력.

        Returns:
            Message: 요청한 범위에서 저장 또는 조회한 결과.
        """
        message = await self.messages.get(query.message_id)
        message.require_recipient(query.peer_id)
        return message

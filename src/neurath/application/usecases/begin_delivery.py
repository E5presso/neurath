"""원 발신자의 최초 전달 또는 확인된 실패의 재전송만 예약한다."""

from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.repositories.message import IMessageRepository
from neurath.domain.aggregates.message import Message
from neurath.domain.errors import ContextNotFound


@immutable
class BeginDeliveryCommand(AbstractCommand):
    """원 발신자의 최초 전달 또는 확인된 실패의 재전송만 예약한다.

    Attributes:
        message_id: 선택한 원 메시지 ID.
        sender_id: 배정 책임이 있는 발신 피어.
    """

    message_id: UUID
    sender_id: UUID


@UseCase()
class BeginDeliveryUseCase(IAsyncCommandUseCase[BeginDeliveryCommand, Message]):
    """원 발신자의 최초 전달 또는 확인된 실패의 재전송만 예약한다."""

    def __init__(self, messages: IMessageRepository) -> None:
        """요청 범위의 조회·저장 계약을 받는다.

        Args:
            messages: Message aggregate의 범위 조회와 저장.
        """
        self.messages = messages

    @transactional
    @override
    async def run(self, command: BeginDeliveryCommand) -> Message:
        """원 발신자의 최초 전달 또는 확인된 실패의 재전송만 예약한다.

        Args:
            command: 원문·수신 범위와 해당 작업에 필요한 입력.

        Returns:
            Message: 요청한 범위에서 저장 또는 조회한 결과.

        Raises:
            ContextNotFound: 요청한 피어·발신자·대화가 지정된 소유 범위와 다른 경우.
        """
        message = await self.messages.get(command.message_id)
        if message.sender_id != command.sender_id:
            raise ContextNotFound("Only the original sender can redrive delivery")
        message.begin_delivery()
        return await self.messages.save(message)

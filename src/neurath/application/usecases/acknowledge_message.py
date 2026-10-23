"""읽은 원 메시지를 ACK하며 작업 수락과 완료는 변경하지 않는다."""

from dataclasses import dataclass
from typing import override

from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.repositories.message import IMessageRepository
from neurath.domain.aggregates.message import Message


@dataclass(frozen=True)
class AcknowledgeMessageCommand(AbstractCommand):
    """읽은 원 메시지를 ACK하며 작업 수락과 완료는 변경하지 않는다.

    Attributes:
        message_id: 선택한 원 메시지 ID.
        peer_id: 호출한 등록 피어.
    """

    message_id: str
    peer_id: str


@UseCase()
class AcknowledgeMessageUseCase(IAsyncCommandUseCase[AcknowledgeMessageCommand, Message]):
    """읽은 원 메시지를 ACK하며 작업 수락과 완료는 변경하지 않는다."""

    def __init__(self, messages: IMessageRepository) -> None:
        """요청 범위의 조회·저장 계약을 받는다.

        Args:
            messages: Message aggregate의 범위 조회와 저장.
        """
        self.messages = messages

    @transactional
    @override
    async def run(self, command: AcknowledgeMessageCommand) -> Message:
        """읽은 원 메시지를 ACK하며 작업 수락과 완료는 변경하지 않는다.

        Args:
            command: 원문·수신 범위와 해당 작업에 필요한 입력.

        Returns:
            Message: 요청한 범위에서 저장 또는 조회한 결과.
        """
        message = await self.messages.get(command.message_id)
        message.acknowledge(command.peer_id)
        return await self.messages.save(message)

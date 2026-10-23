"""기존 제출의 관찰만 저장하며 조회·늦은 응답으로 메시지를 다시 보내지 않는다."""

from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.repositories.message import IMessageRepository
from neurath.domain.aggregates.message import DeliveryStatus, Message


@immutable
class RecordDeliveryCommand(AbstractCommand):
    """기존 제출의 관찰만 저장하며 조회·늦은 응답으로 메시지를 다시 보내지 않는다.

    Attributes:
        message_id: 선택한 원 메시지 ID.
        attempt: 관찰한 원 제출 번호.
        status: 호스트에서 실제 관찰한 전달 결과.
        evidence: 호스트 전달 결과 또는 미전달 실패의 근거.
    """

    message_id: UUID
    attempt: int
    status: DeliveryStatus
    evidence: str


@UseCase()
class RecordDeliveryUseCase(IAsyncCommandUseCase[RecordDeliveryCommand, Message]):
    """기존 제출의 관찰만 저장하며 조회·늦은 응답으로 메시지를 다시 보내지 않는다."""

    def __init__(self, messages: IMessageRepository) -> None:
        """요청 범위의 조회·저장 계약을 받는다.

        Args:
            messages: Message aggregate의 범위 조회와 저장.
        """
        self.messages = messages

    @transactional
    @override
    async def run(self, command: RecordDeliveryCommand) -> Message:
        """기존 제출의 관찰만 저장하며 조회·늦은 응답으로 메시지를 다시 보내지 않는다.

        Args:
            command: 원문·수신 범위와 해당 작업에 필요한 입력.

        Returns:
            Message: 요청한 범위에서 저장 또는 조회한 결과.
        """
        message = await self.messages.get(command.message_id)
        message.observe_delivery(command.attempt, command.status, command.evidence)
        return await self.messages.save(message)

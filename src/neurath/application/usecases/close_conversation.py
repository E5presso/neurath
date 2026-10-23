"""참가자의 대화를 종료하며 메시지와 미완료 배정은 보존한다."""

from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.repositories.conversation import IConversationRepository
from neurath.domain.aggregates.conversation import Conversation


@immutable
class CloseConversationCommand(AbstractCommand):
    """참가자의 대화를 종료하며 메시지와 미완료 배정은 보존한다.

    Attributes:
        conversation_id: 참여 중인 원 대화.
        peer_id: 호출한 등록 피어.
    """

    conversation_id: UUID
    peer_id: UUID


@UseCase()
class CloseConversationUseCase(IAsyncCommandUseCase[CloseConversationCommand, Conversation]):
    """참가자의 대화를 종료하며 메시지와 미완료 배정은 보존한다."""

    def __init__(self, conversations: IConversationRepository) -> None:
        """요청 범위의 조회·저장 계약을 받는다.

        Args:
            conversations: Conversation aggregate의 범위 조회와 저장.
        """
        self.conversations = conversations

    @transactional
    @override
    async def run(self, command: CloseConversationCommand) -> Conversation:
        """참가자의 대화를 종료하며 메시지와 미완료 배정은 보존한다.

        Args:
            command: 원문·수신 범위와 해당 작업에 필요한 입력.

        Returns:
            Conversation: 요청한 범위에서 저장 또는 조회한 결과.
        """
        conversation = await self.conversations.get(command.conversation_id)
        conversation.close(command.peer_id)
        return await self.conversations.save(conversation)

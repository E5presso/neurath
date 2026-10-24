"""같은 동료 메시지를 재시도해도 대화와 본문을 중복 생성하지 않는다."""

from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.repositories.conversation import IConversationRepository
from neurath.application.ports.repositories.message import IMessageRepository
from neurath.application.ports.repositories.peer import IPeerRepository
from neurath.domain.aggregates.conversation import Conversation
from neurath.domain.aggregates.message import Message
from neurath.domain.errors import InvalidTaskState


@immutable
class SendPeerMessageCommand(AbstractCommand):
    """명시한 동료에게 보낼 실제 원문과 재전송 식별값이다.

    Attributes:
        sender_id: 실제 발신 피어.
        recipient_id: 실제 수신 피어.
        key: 같은 메시지를 재전송할 때 유지하는 값.
        title: 제목 알림.
        body: 원문 전체.
    """

    sender_id: UUID
    recipient_id: UUID
    key: str
    title: str
    body: str


@UseCase()
class SendPeerMessageUseCase(IAsyncCommandUseCase[SendPeerMessageCommand, Message]):
    """실제 전송 효과와 구분되는 대화·메시지 저장을 하나의 요청으로 처리한다."""

    def __init__(
        self,
        peers: IPeerRepository,
        messages: IMessageRepository,
        conversations: IConversationRepository,
    ) -> None:
        """실제 주소와 원 메시지·대화의 저장 계약을 받는다.

        Args:
            peers: 실제 연결한 동료 확인.
            messages: 동일 원 메시지 조회와 저장.
            conversations: 처음 전달하는 대화 연결.
        """
        self.peers = peers
        self.messages = messages
        self.conversations = conversations

    @transactional
    @override
    async def run(self, command: SendPeerMessageCommand) -> Message:
        """같은 원문은 재사용하고 바뀐 본문을 같은 전송으로 덮어쓰지 않는다.

        Args:
            command: 동료 주소와 원문.

        Returns:
            Message: 새 메시지 또는 동일 요청의 기존 메시지.

        Raises:
            InvalidTaskState: 같은 키로 다른 본문을 전달하려는 경우.
        """
        prior = await self.messages.find_by_sender_id_and_recipient_id_and_key(
            command.sender_id, command.recipient_id, command.key
        )
        if prior is not None:
            if (prior.title, prior.body) != (command.title, command.body):
                raise InvalidTaskState("A retry cannot replace the original message")
            return prior
        sender = await self.peers.get(command.sender_id)
        sender.require_active()
        await self.peers.get(command.recipient_id)
        conversation = Conversation(
            uid=Conversation.next_id(), participants=(command.sender_id, command.recipient_id)
        )
        message = Message(
            uid=Message.next_id(),
            conversation_id=conversation.uid,
            sender_id=command.sender_id,
            recipient_id=command.recipient_id,
            key=command.key,
            title=command.title,
            body=command.body,
        )
        await self.conversations.save(conversation)
        return await self.messages.save(message)

"""검증한 원 메시지를 인박스에 저장하고 동일 발신 키의 재시도는 원문을 반환한다."""

from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.repositories.conversation import IConversationRepository
from neurath.application.ports.repositories.message import IMessageRepository
from neurath.application.ports.repositories.peer import IPeerRepository
from neurath.domain.aggregates.message import Message
from neurath.domain.errors import ContextNotFound, InvalidTaskState


@immutable
class SendMessageCommand(AbstractCommand):
    """검증한 원 메시지를 인박스에 저장하고 동일 발신 키의 재시도는 원문을 반환한다.

    Attributes:
        conversation_id: 참여 중인 원 대화.
        sender_id: 배정 책임이 있는 발신 피어.
        recipient_id: 실제 등록된 수신 피어.
        key: 재시도에서 재사용할 발신 키.
        title: 인박스용 제목.
        body: 원래 전체 본문.
        reply_to: 답장 대상인 원 메시지.
    """

    conversation_id: UUID
    sender_id: UUID
    recipient_id: UUID
    key: str
    title: str
    body: str
    reply_to: UUID | None = None


@UseCase()
class SendMessageUseCase(IAsyncCommandUseCase[SendMessageCommand, Message]):
    """검증한 원 메시지를 인박스에 저장하고 동일 발신 키의 재시도는 원문을 반환한다."""

    def __init__(
        self,
        conversations: IConversationRepository,
        peers: IPeerRepository,
        messages: IMessageRepository,
    ) -> None:
        """요청 범위의 조회·저장 계약을 받는다.

        Args:
            conversations: Conversation aggregate의 범위 조회와 저장.
            peers: Peer aggregate의 범위 조회와 저장.
            messages: Message aggregate의 범위 조회와 저장.
        """
        self.conversations = conversations
        self.peers = peers
        self.messages = messages

    @transactional
    @override
    async def run(self, command: SendMessageCommand) -> Message:
        """검증한 원 메시지를 인박스에 저장하고 동일 발신 키의 재시도는 원문을 반환한다.

        Args:
            command: 원문·수신 범위와 해당 작업에 필요한 입력.

        Returns:
            Message: 요청한 범위에서 저장 또는 조회한 결과.

        Raises:
            ContextNotFound: 요청한 피어·발신자·대화가 지정된 소유 범위와 다른 경우.
            InvalidTaskState: 최신 배정·수신 경로·원문과 충돌하는 요청인 경우.
        """
        conversation = await self.conversations.get(command.conversation_id)
        conversation.require_participant(command.sender_id)
        conversation.require_participant(command.recipient_id)
        existing = await self.messages.find_by_sender_id_and_recipient_id_and_key(
            command.sender_id, command.recipient_id, command.key
        )
        if existing is not None:
            if (
                existing.conversation_id,
                existing.title,
                existing.body,
                existing.reply_to,
                existing.topic,
            ) != (
                command.conversation_id,
                command.title,
                command.body,
                command.reply_to,
                None,
            ):
                raise InvalidTaskState("A message retry must preserve the original envelope")
            return existing
        conversation.require_open()
        (await self.peers.get(command.sender_id)).require_active()
        await self.peers.get(command.recipient_id)
        if command.reply_to is not None:
            original = await self.messages.get(command.reply_to)
            if original.conversation_id != conversation.uid:
                raise ContextNotFound("Reply must stay in the original conversation")
        message = Message(
            uid=Message.next_id(),
            conversation_id=conversation.uid,
            sender_id=command.sender_id,
            recipient_id=command.recipient_id,
            key=command.key,
            title=command.title,
            body=command.body,
            reply_to=command.reply_to,
        )
        return await self.messages.save(message)

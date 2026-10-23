"""대화 참가자 중 활성 구독자에게만 발행하고 재시도는 원 수신자 목록을 유지한다."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import override

from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.repositories.conversation import IConversationRepository
from neurath.application.ports.repositories.message import IMessageRepository
from neurath.application.ports.repositories.peer import IPeerRepository
from neurath.domain.aggregates.message import Message
from neurath.domain.errors import InvalidTaskState


@dataclass(frozen=True)
class PublishMessageCommand(AbstractCommand):
    """대화 참가자 중 활성 구독자에게만 발행하고 재시도는 원 수신자 목록을 유지한다.

    Attributes:
        conversation_id: 참여 중인 원 대화.
        sender_id: 배정 책임이 있는 발신 피어.
        topic: 수신자가 명시적으로 구독한 주제.
        key: 재시도에서 재사용할 발신 키.
        title: 인박스용 제목.
        body: 원래 전체 본문.
    """

    conversation_id: str
    sender_id: str
    topic: str
    key: str
    title: str
    body: str


@UseCase()
class PublishMessageUseCase(IAsyncCommandUseCase[PublishMessageCommand, Sequence[Message]]):
    """대화 참가자 중 활성 구독자에게만 발행하고 재시도는 원 수신자 목록을 유지한다."""

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
    async def run(self, command: PublishMessageCommand) -> Sequence[Message]:
        """대화 참가자 중 활성 구독자에게만 발행하고 재시도는 원 수신자 목록을 유지한다.

        Args:
            command: 원문·수신 범위와 해당 작업에 필요한 입력.

        Returns:
            Sequence[Message]: 요청한 범위에서 저장 또는 조회한 결과.

        Raises:
            InvalidTaskState: 최신 배정·수신 경로·원문과 충돌하는 요청인 경우.
            ValueError: 필수 입력이나 실제 지원 모델·정책이 유효하지 않은 경우.
        """
        conversation = await self.conversations.get(command.conversation_id)
        conversation.require_participant(command.sender_id)
        if not command.topic.strip():
            raise ValueError("Publication topic must be non-empty")
        existing = await self.messages.find_by_sender_id_and_key(command.sender_id, command.key)
        if existing:
            if any(
                (m.conversation_id, m.title, m.body, m.topic)
                != (command.conversation_id, command.title, command.body, command.topic)
                for m in existing
            ):
                raise InvalidTaskState("Publication retry must preserve its original envelope")
            return existing
        conversation.require_open()
        (await self.peers.get(command.sender_id)).require_active()
        messages: list[Message] = []
        for peer_id in conversation.participants:
            if peer_id == command.sender_id:
                continue
            recipient = await self.peers.get(peer_id)
            if not recipient.active or command.topic not in recipient.subscriptions:
                continue
            message = Message(
                uid=Message.next_id(),
                conversation_id=conversation.uid,
                sender_id=command.sender_id,
                recipient_id=recipient.uid,
                key=command.key,
                title=command.title,
                body=command.body,
                topic=command.topic,
            )
            messages.append(await self.messages.save(message))
        return tuple(messages)

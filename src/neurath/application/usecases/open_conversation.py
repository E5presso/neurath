"""명시된 실제 피어만 연결한 대화를 열며 프로젝트 간 자료를 자동 공유하지 않는다."""

from collections.abc import Sequence
from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.repositories.conversation import IConversationRepository
from neurath.application.ports.repositories.peer import IPeerRepository
from neurath.domain.aggregates.conversation import Conversation


@immutable
class OpenConversationCommand(AbstractCommand):
    """명시된 실제 피어만 연결한 대화를 열며 프로젝트 간 자료를 자동 공유하지 않는다.

    Attributes:
        participants: 명시적으로 연결할 피어 목록.
    """

    participants: Sequence[UUID]


@UseCase()
class OpenConversationUseCase(IAsyncCommandUseCase[OpenConversationCommand, Conversation]):
    """명시된 실제 피어만 연결한 대화를 열며 프로젝트 간 자료를 자동 공유하지 않는다."""

    def __init__(self, peers: IPeerRepository, conversations: IConversationRepository) -> None:
        """요청 범위의 조회·저장 계약을 받는다.

        Args:
            peers: Peer aggregate의 범위 조회와 저장.
            conversations: Conversation aggregate의 범위 조회와 저장.
        """
        self.peers = peers
        self.conversations = conversations

    @transactional
    @override
    async def run(self, command: OpenConversationCommand) -> Conversation:
        """명시된 실제 피어만 연결한 대화를 열며 프로젝트 간 자료를 자동 공유하지 않는다.

        Args:
            command: 원문·수신 범위와 해당 작업에 필요한 입력.

        Returns:
            Conversation: 요청한 범위에서 저장 또는 조회한 결과.
        """
        conversation = Conversation(uid=Conversation.next_id(), participants=command.participants)
        for peer_id in command.participants:
            await self.peers.get(peer_id)
        return await self.conversations.save(conversation)

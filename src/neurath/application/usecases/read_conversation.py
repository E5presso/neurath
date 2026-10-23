"""원 대화의 참가자와 종료 여부를 기록 변경 없이 조회한다."""

from dataclasses import dataclass
from typing import override

from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.query import AbstractQuery, IAsyncQueryUseCase

from neurath.application.ports.repositories.conversation import IConversationRepository
from neurath.domain.aggregates.conversation import Conversation


@dataclass(frozen=True)
class ReadConversationQuery(AbstractQuery):
    """원 대화의 참가자와 종료 여부를 기록 변경 없이 조회한다.

    Attributes:
        conversation_id: 참여 중인 원 대화.
        peer_id: 호출한 등록 피어.
    """

    conversation_id: str
    peer_id: str


@UseCase()
class ReadConversationUseCase(IAsyncQueryUseCase[ReadConversationQuery, Conversation]):
    """원 대화의 참가자와 종료 여부를 기록 변경 없이 조회한다."""

    def __init__(self, conversations: IConversationRepository) -> None:
        """요청 범위의 조회·저장 계약을 받는다.

        Args:
            conversations: Conversation aggregate의 범위 조회와 저장.
        """
        self.conversations = conversations

    @transactional
    @override
    async def run(self, query: ReadConversationQuery) -> Conversation:
        """원 대화의 참가자와 종료 여부를 기록 변경 없이 조회한다.

        Args:
            query: 원문·수신 범위와 해당 작업에 필요한 입력.

        Returns:
            Conversation: 요청한 범위에서 저장 또는 조회한 결과.
        """
        conversation = await self.conversations.get(query.conversation_id)
        conversation.require_participant(query.peer_id)
        return conversation

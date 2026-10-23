"""참가자와 대화 종료를 작업 완료와 별도로 관리한다."""

from collections.abc import Sequence
from typing import override
from uuid import uuid4

from spakky.core.common.mutability import mutable
from spakky.domain.models.aggregate_root import AbstractAggregateRoot

from neurath.domain.errors import ContextNotFound, InvalidTaskState


@mutable
class Conversation(AbstractAggregateRoot[str]):
    """명시적으로 연결한 피어 사이의 대화다. 종료해도 메시지는 보존한다.

    Attributes:
        participants: 대화에 참여하는 피어 ID.
        closed: 새 발신을 받지 않는 종료 상태.
        revision: 저장소 낙관적 버전.
    """

    participants: Sequence[str]
    closed: bool = False
    revision: int = 1

    @classmethod
    @override
    def next_id(cls) -> str:
        """답장에서 재사용할 대화 ID를 생성한다.

        Returns:
            str: 새 대화 식별자.
        """
        return str(uuid4())

    @override
    def validate(self) -> None:
        """중복되거나 부족한 참가자를 거부한다.

        Raises:
            ValueError: 서로 다른 두 피어 이상이 아닌 경우.
        """
        if len(set(self.participants)) != len(self.participants) or len(self.participants) < 2:
            raise ValueError("Conversation requires distinct participants")

    def require_participant(self, peer_id: str) -> None:
        """대화 밖 피어의 본문 조회와 변경을 거부한다.

        Args:
            peer_id: 요청한 피어 ID.

        Raises:
            ContextNotFound: 대화 참가자가 아닌 경우.
        """
        if peer_id not in self.participants:
            raise ContextNotFound("Peer is outside this conversation")

    def require_open(self) -> None:
        """대화 종료 후 신규 발신을 거부한다.

        Raises:
            InvalidTaskState: 이미 종료한 대화인 경우.
        """
        if self.closed:
            raise InvalidTaskState("Conversation is closed")

    def close(self, peer_id: str) -> None:
        """참가자의 대화를 닫되 미완료 태스크와 메시지는 변경하지 않는다.

        Args:
            peer_id: 종료를 요청한 참가자.
        """
        self.require_participant(peer_id)
        self.closed = True

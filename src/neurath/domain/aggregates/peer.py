"""실제 호스트 세션 주소와 피어의 수신 구독을 보존한다."""

from collections.abc import Sequence
from typing import override
from uuid import uuid4

from spakky.core.common.mutability import mutable
from spakky.domain.models.aggregate_root import AbstractAggregateRoot

from neurath.domain.errors import InvalidTaskState


@mutable
class Peer(AbstractAggregateRoot[str]):
    """등록된 세션과 선택적 네이티브 자식 주소를 가진 수신자다.

    Attributes:
        session_id: 실제 관찰된 HostSession 식별자.
        agent_id: 네이티브 자식 식별자이며 루트면 빈 문자열.
        active: 다음 훅에서 수신할 수 있는지 여부.
        subscriptions: 명시적으로 구독한 주제.
        current_delegation_id: 이 피어가 수락해 현재 수행하는 배정.
        revision: 저장소 낙관적 버전.
    """

    session_id: str
    agent_id: str = ""
    active: bool = True
    subscriptions: Sequence[str] = ()
    current_delegation_id: str | None = None
    revision: int = 1

    @classmethod
    @override
    def next_id(cls) -> str:
        """재연결 때 재사용할 피어 식별자를 생성한다.

        Returns:
            str: 새로운 피어 ID.
        """
        return str(uuid4())

    def subscribe(self, topics: Sequence[str]) -> None:
        """구독 목록만 교체하며 이미 전달한 메시지에는 영향을 주지 않는다.

        Args:
            topics: 이후 발행에서 받을 주제 목록.

        Raises:
            ValueError: 주제가 공백이거나 중복인 경우.
        """
        if any(not topic.strip() for topic in topics) or len(set(topics)) != len(topics):
            raise ValueError("Subscriptions must be non-empty and unique")
        self.subscriptions = topics

    def require_active(self) -> None:
        """종료·대기 피어를 새 작업의 수신자로 사용하지 못하게 한다.

        Raises:
            InvalidTaskState: 수신자가 비활성 상태인 경우.
        """
        if not self.active:
            raise InvalidTaskState("Peer is not active")

    def accept_assignment(self, delegation_id: str) -> None:
        """수신자가 수락한 한 배정을 현재 실행 범위로 연결한다.

        Args:
            delegation_id: 수락 조건을 확인한 배정 ID.

        Raises:
            InvalidTaskState: 이미 다른 배정을 수행하는 경우.
        """
        if self.current_delegation_id not in (None, delegation_id):
            raise InvalidTaskState("Finish or stop the current assignment before accepting another")
        self.current_delegation_id = delegation_id

    def finish_assignment(self, delegation_id: str) -> None:
        """같은 배정의 보고·중단 후에만 현재 실행 연결을 해제한다.

        Args:
            delegation_id: 실제 보고 또는 중단 확인이 끝난 배정.
        """
        if self.current_delegation_id == delegation_id:
            self.current_delegation_id = None

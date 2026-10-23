"""저장·전달·본문 열람·ACK를 구분하는 메시지 원장이다."""

from enum import StrEnum
from typing import override
from uuid import UUID, uuid7

from spakky.core.common.mutability import mutable
from spakky.domain.models.aggregate_root import AbstractAggregateRoot

from neurath.domain.errors import ContextNotFound, InvalidTaskState


class DeliveryStatus(StrEnum):
    """호스트 제출 결과이며 열람이나 작업 수락을 뜻하지 않는다.

    Attributes:
        PENDING: 아직 전달을 시작하지 않음.
        UNKNOWN: 제출을 시작했으나 결과가 확정되지 않음.
        DELIVERED: 수신 경계에서 전달을 확인함.
        FAILED: 재전송 가능한 미전달 실패를 확인함.
    """

    PENDING = "pending"
    UNKNOWN = "unknown"
    DELIVERED = "delivered"
    FAILED = "failed"


@mutable
class Message(AbstractAggregateRoot[UUID]):
    """한 수신자에게 보낸 원문과 읽음·전달 상태를 독립적으로 보존한다.

    Attributes:
        conversation_id: 원래 대화 ID.
        sender_id: 실제 등록된 발신 피어.
        recipient_id: 확정된 수신 피어.
        key: 발신자가 재시도 때 재사용하는 메시지 키.
        title: 인박스에 노출할 짧은 제목.
        body: 선택 조회할 원래 전체 본문.
        reply_to: 답장이 참조하는 원 메시지.
        topic: 구독 발행의 원 주제이며 직접 메시지면 None.
        status: 현재 전달 관찰.
        delivery_attempt: 명시적 제출 횟수.
        delivery_evidence: 마지막 제출의 진단 또는 전달 근거.
        read: 수신자가 본문을 읽은 사실.
        acknowledged: 읽은 원 메시지의 ACK.
        revision: 저장소 낙관적 버전.
    """

    conversation_id: UUID
    sender_id: UUID
    recipient_id: UUID
    key: str
    title: str
    body: str
    reply_to: UUID | None = None
    topic: str | None = None
    status: DeliveryStatus = DeliveryStatus.PENDING
    delivery_attempt: int = 0
    delivery_evidence: str | None = None
    read: bool = False
    acknowledged: bool = False
    revision: int = 1

    @classmethod
    @override
    def next_id(cls) -> UUID:
        """재전송에도 바뀌지 않을 원 메시지 ID를 생성한다.

        Returns:
            UUID: 새 메시지 ID.
        """
        return uuid7()

    @override
    def validate(self) -> None:
        """빈 원문·자기 발신·과도한 본문을 저장 전에 거부한다.

        Raises:
            ValueError: 메시지 필수 정보 또는 크기가 잘못된 경우.
        """
        if not all(value.strip() for value in (self.key, self.title, self.body)):
            raise ValueError("Message key, title and body must be non-empty")
        if self.topic is not None and not self.topic.strip():
            raise ValueError("Publication topic must be non-empty")
        if self.sender_id == self.recipient_id or len(self.body.encode()) > 1048576:
            raise ValueError("Message recipient or size is invalid")

    def require_recipient(self, peer_id: UUID) -> None:
        """원래 수신자가 아닌 피어의 읽음·ACK 변경을 거부한다.

        Args:
            peer_id: 읽거나 ACK하는 피어.

        Raises:
            ContextNotFound: 수신자가 다른 경우.
        """
        if peer_id != self.recipient_id:
            raise ContextNotFound("Message belongs to another recipient")

    def begin_delivery(self) -> int:
        """최초 또는 확인된 미전달 실패만 제출하고 불명 결과는 재전송하지 않는다.

        Returns:
            int: 관찰 결과와 대조할 제출 번호.

        Raises:
            InvalidTaskState: 이미 전달됐거나 결과가 불명인 경우.
        """
        if self.status not in (DeliveryStatus.PENDING, DeliveryStatus.FAILED) or self.read:
            raise InvalidTaskState("Only an unsent or confirmed failed message can be delivered")
        self.delivery_attempt += 1
        self.status = DeliveryStatus.UNKNOWN
        return self.delivery_attempt

    def observe_delivery(self, attempt: int, status: DeliveryStatus, evidence: str) -> None:
        """같은 제출의 관찰만 반영하고 늦은 실패로 읽음·ACK를 되돌리지 않는다.

        Args:
            attempt: 실제 관찰한 제출 번호.
            status: 전달·실패·불명 중 관찰한 상태.
            evidence: 호스트 결과 또는 실패 진단.

        Raises:
            ValueError: 미제출 상태나 빈 관찰을 결과로 사용한 경우.
        """
        if status is DeliveryStatus.PENDING or not evidence.strip():
            raise ValueError("A delivery observation requires status and evidence")
        if attempt != self.delivery_attempt or self.read or self.status is DeliveryStatus.DELIVERED:
            return
        self.status = status
        self.delivery_evidence = evidence

    def mark_read(self, peer_id: UUID) -> None:
        """본문을 반환하는 수신자 조회에서만 읽음을 기록한다.

        Args:
            peer_id: 본문을 요청한 원 수신자.
        """
        self.require_recipient(peer_id)
        self.read = True
        self.status = DeliveryStatus.DELIVERED

    def acknowledge(self, peer_id: UUID) -> None:
        """읽은 메시지만 ACK하며 배정 수락·태스크 완료는 변경하지 않는다.

        Args:
            peer_id: ACK를 보내는 원 수신자.

        Raises:
            InvalidTaskState: 본문을 아직 읽지 않은 경우.
        """
        self.require_recipient(peer_id)
        if not self.read:
            raise InvalidTaskState("Read the original message before acknowledging it")
        self.acknowledged = True

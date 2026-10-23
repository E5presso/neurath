"""Message의 주소·범위·관찰 이력을 선언형 테이블로 보존한다."""

from datetime import UTC, datetime
from typing import Self, override
from uuid import UUID

from spakky.plugins.sqlalchemy.orm.table import AbstractMappableTable, Table
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from neurath.domain.aggregates.message import DeliveryStatus, Message


@Table(Message)
class MessageModel(AbstractMappableTable[Message]):
    """Message의 저장 상태와 낙관적 개정을 왕복한다.

    Attributes:
        id: 도메인의 안정적인 식별자.
        version: 프레임워크가 관리하는 변경 토큰.
        created_at: 최초 생성 UTC 시각.
        updated_at: 마지막 변경 UTC 시각.
        revision: 저장소 낙관적 버전.
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
    """

    __tablename__ = "core_messages"
    __table_args__ = (UniqueConstraint("sender_id", "recipient_id", "key"),)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    version: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    conversation_id: Mapped[str] = mapped_column(
        String, ForeignKey("core_conversations.id"), nullable=False
    )
    sender_id: Mapped[str] = mapped_column(String, ForeignKey("core_peers.id"), nullable=False)
    recipient_id: Mapped[str] = mapped_column(String, ForeignKey("core_peers.id"), nullable=False)
    key: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    body: Mapped[str] = mapped_column(String, nullable=False)
    reply_to: Mapped[str | None] = mapped_column(
        String, ForeignKey("core_messages.id"), nullable=True
    )
    topic: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    delivery_attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    delivery_evidence: Mapped[str | None] = mapped_column(String, nullable=True)
    read: Mapped[bool] = mapped_column(Boolean, nullable=False)
    acknowledged: Mapped[bool] = mapped_column(Boolean, nullable=False)
    __mapper_args__ = {"version_id_col": revision}

    @classmethod
    @override
    def from_domain(cls, domain: Message) -> Self:
        """범위와 원문·관찰을 저장할 레코드로 변환한다.

        Args:
            domain: 저장할 Message.

        Returns:
            Self: 원문을 보존한 저장 레코드.
        """
        return cls(
            id=domain.uid,
            version=domain.version,
            created_at=domain.created_at.astimezone(UTC).replace(tzinfo=None),
            updated_at=domain.updated_at.astimezone(UTC).replace(tzinfo=None),
            revision=domain.revision,
            conversation_id=domain.conversation_id,
            sender_id=domain.sender_id,
            recipient_id=domain.recipient_id,
            key=domain.key,
            title=domain.title,
            body=domain.body,
            reply_to=domain.reply_to,
            topic=domain.topic,
            status=domain.status.value,
            delivery_attempt=domain.delivery_attempt,
            delivery_evidence=domain.delivery_evidence,
            read=domain.read,
            acknowledged=domain.acknowledged,
        )

    @override
    def to_domain(self) -> Message:
        """저장된 원문·관찰을 요청과 독립적인 도메인 객체로 복원한다.

        Returns:
            Message: 저장된 현재 상태와 과거 관찰.
        """
        return Message(
            uid=self.id,
            version=self.version,
            created_at=self.created_at.replace(tzinfo=UTC),
            updated_at=self.updated_at.replace(tzinfo=UTC),
            revision=self.revision,
            conversation_id=self.conversation_id,
            sender_id=self.sender_id,
            recipient_id=self.recipient_id,
            key=self.key,
            title=self.title,
            body=self.body,
            reply_to=self.reply_to,
            topic=self.topic,
            status=DeliveryStatus(self.status),
            delivery_attempt=self.delivery_attempt,
            delivery_evidence=self.delivery_evidence,
            read=self.read,
            acknowledged=self.acknowledged,
        )

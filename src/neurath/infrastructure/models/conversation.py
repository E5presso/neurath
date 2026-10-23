"""Conversation의 주소·범위·관찰 이력을 선언형 테이블로 보존한다."""

from datetime import UTC, datetime
from typing import Self, override
from uuid import UUID

from spakky.plugins.sqlalchemy.orm.table import AbstractMappableTable, Table
from sqlalchemy import JSON, Boolean, DateTime, Integer, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from neurath.domain.aggregates.conversation import Conversation


@Table(Conversation)
class ConversationModel(AbstractMappableTable[Conversation]):
    """Conversation의 저장 상태와 낙관적 개정을 왕복한다.

    Attributes:
        id: 도메인의 안정적인 식별자.
        version: 프레임워크가 관리하는 변경 토큰.
        created_at: 최초 생성 UTC 시각.
        updated_at: 마지막 변경 UTC 시각.
        revision: 저장소 낙관적 버전.
        participants: 대화에 참여하는 피어 ID.
        closed: 새 발신을 받지 않는 종료 상태.
    """

    __tablename__ = "core_conversations"
    id: Mapped[UUID] = mapped_column(Uuid(), primary_key=True)
    version: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    participants: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    closed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    __mapper_args__ = {"version_id_col": revision}

    @classmethod
    @override
    def from_domain(cls, domain: Conversation) -> Self:
        """범위와 원문·관찰을 저장할 레코드로 변환한다.

        Args:
            domain: 저장할 Conversation.

        Returns:
            Self: 원문을 보존한 저장 레코드.
        """
        return cls(
            id=domain.uid,
            version=domain.version,
            created_at=domain.created_at.astimezone(UTC).replace(tzinfo=None),
            updated_at=domain.updated_at.astimezone(UTC).replace(tzinfo=None),
            revision=domain.revision,
            participants=[str(uid) for uid in domain.participants],
            closed=domain.closed,
        )

    @override
    def to_domain(self) -> Conversation:
        """저장된 원문·관찰을 요청과 독립적인 도메인 객체로 복원한다.

        Returns:
            Conversation: 저장된 현재 상태와 과거 관찰.
        """
        return Conversation(
            uid=self.id,
            version=self.version,
            created_at=self.created_at.replace(tzinfo=UTC),
            updated_at=self.updated_at.replace(tzinfo=UTC),
            revision=self.revision,
            participants=[UUID(uid) for uid in self.participants],
            closed=self.closed,
        )

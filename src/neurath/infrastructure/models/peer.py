"""Peer의 주소·범위·관찰 이력을 선언형 테이블로 보존한다."""

from datetime import UTC, datetime
from typing import Self, override
from uuid import UUID

from spakky.plugins.sqlalchemy.orm.table import AbstractMappableTable, Table
from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from neurath.domain.aggregates.peer import Peer


@Table(Peer)
class PeerModel(AbstractMappableTable[Peer]):
    """Peer의 저장 상태와 낙관적 개정을 왕복한다.

    Attributes:
        id: 도메인의 안정적인 식별자.
        version: 프레임워크가 관리하는 변경 토큰.
        created_at: 최초 생성 UTC 시각.
        updated_at: 마지막 변경 UTC 시각.
        revision: 저장소 낙관적 버전.
        session_id: 실제 관찰된 HostSession 식별자.
        agent_id: 네이티브 자식 식별자이며 루트면 빈 문자열.
        active: 다음 훅에서 수신할 수 있는지 여부.
        subscriptions: 명시적으로 구독한 주제.
        current_delegation_id: 현재 수락한 배정의 연결.
    """

    __tablename__ = "core_peers"
    __table_args__ = (UniqueConstraint("session_id", "agent_id"),)
    id: Mapped[UUID] = mapped_column(Uuid(), primary_key=True)
    version: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    session_id: Mapped[UUID] = mapped_column(Uuid(), ForeignKey("core_sessions.id"), nullable=False)
    agent_id: Mapped[str] = mapped_column(String, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    subscriptions: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    current_delegation_id: Mapped[UUID | None] = mapped_column(Uuid(), nullable=True)
    __mapper_args__ = {"version_id_col": revision}

    @classmethod
    @override
    def from_domain(cls, domain: Peer) -> Self:
        """범위와 원문·관찰을 저장할 레코드로 변환한다.

        Args:
            domain: 저장할 Peer.

        Returns:
            Self: 원문을 보존한 저장 레코드.
        """
        return cls(
            id=domain.uid,
            version=domain.version,
            created_at=domain.created_at.astimezone(UTC).replace(tzinfo=None),
            updated_at=domain.updated_at.astimezone(UTC).replace(tzinfo=None),
            revision=domain.revision,
            session_id=domain.session_id,
            agent_id=domain.agent_id,
            active=domain.active,
            subscriptions=list(domain.subscriptions),
            current_delegation_id=domain.current_delegation_id,
        )

    @override
    def to_domain(self) -> Peer:
        """저장된 원문·관찰을 요청과 독립적인 도메인 객체로 복원한다.

        Returns:
            Peer: 저장된 현재 상태와 과거 관찰.
        """
        return Peer(
            uid=self.id,
            version=self.version,
            created_at=self.created_at.replace(tzinfo=UTC),
            updated_at=self.updated_at.replace(tzinfo=UTC),
            revision=self.revision,
            session_id=self.session_id,
            agent_id=self.agent_id,
            active=self.active,
            subscriptions=self.subscriptions,
            current_delegation_id=self.current_delegation_id,
        )

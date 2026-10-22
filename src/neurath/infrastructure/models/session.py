"""명시적인 필드 변환으로 호스트 세션을 선언적으로 매핑한다."""

from datetime import UTC, datetime
from typing import Self, override
from uuid import UUID

from spakky.plugins.sqlalchemy.orm.table import AbstractMappableTable, Table
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from neurath.domain.aggregates.session import HostSession


@Table(HostSession)
class SessionModel(AbstractMappableTable[HostSession]):
    """범위가 지정된 네이티브 식별자와 작업 경로의 낙관적 버전을 저장한다.

    Attributes:
        id: 저장된 엔티티의 안정적인 식별자.
        version: 프레임워크가 관리하는 도메인 변경 토큰.
        created_at: 최초 메타데이터이며 이전 자료는 미상 시각을 나타내는 epoch.
        updated_at: 마지막으로 변경한 도메인 시각.
        project_id: 조회 대상 프로젝트의 안정적인 식별자.
        provider: 네이티브 세션 식별자의 호스트 공급자 이름 공간.
        host_session_id: 호스트 공급자가 전달한 네이티브 세션 식별자.
        working_directory: 가장 최근에 수용한 정규 작업 디렉터리.
        revision: 쓰기 시 SQLAlchemy가 생성하여 저장한 낙관적 버전.
        successor_id: 작업 인수가 확정된 후속 세션 ID.
    """

    __tablename__ = "core_sessions"
    __table_args__ = (
        UniqueConstraint("project_id", "provider", "host_session_id", name="uq_core_host_session"),
        UniqueConstraint("project_id", "id", name="uq_core_session_scope"),
        CheckConstraint("revision >= 1", name="session_revision_positive"),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True)
    version: Mapped[UUID] = mapped_column(
        Uuid(), nullable=False, server_default="00000000000000000000000000000000"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="1970-01-01 00:00:00"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="1970-01-01 00:00:00"
    )

    project_id: Mapped[str] = mapped_column(String, ForeignKey("core_projects.id"), nullable=False)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    host_session_id: Mapped[str] = mapped_column(String, nullable=False)
    working_directory: Mapped[str] = mapped_column(String, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)

    successor_id: Mapped[str | None] = mapped_column(String)

    __mapper_args__ = {"version_id_col": revision}

    @classmethod
    @override
    def from_domain(cls, domain: HostSession) -> Self:
        """세션의 식별자·경로·revision과 UTC 기준 시각을 ORM 객체에 복사한다.

        Args:
            domain: 현재 트랜잭션에 저장할 도메인 세션 엔티티.

        Returns:
            Self: 도메인 필드를 명시적으로 복사한 새 저장 레코드.
        """
        return cls(
            id=domain.uid,
            version=domain.version,
            created_at=domain.created_at.astimezone(UTC).replace(tzinfo=None),
            updated_at=domain.updated_at.astimezone(UTC).replace(tzinfo=None),
            project_id=domain.project_id,
            provider=domain.provider,
            host_session_id=domain.host_session_id,
            working_directory=domain.working_directory,
            revision=domain.revision,
            successor_id=domain.successor_id,
        )

    @override
    def to_domain(self) -> HostSession:
        """저장 시각에 UTC를 복원하여 ORM 수명과 분리된 호스트 세션을 만든다.

        Returns:
            HostSession: 저장된 버전을 가진 분리된 세션 엔티티.
        """
        return HostSession(
            uid=self.id,
            version=self.version,
            created_at=self.created_at.replace(tzinfo=UTC),
            updated_at=self.updated_at.replace(tzinfo=UTC),
            project_id=self.project_id,
            provider=self.provider,
            host_session_id=self.host_session_id,
            working_directory=self.working_directory,
            revision=self.revision,
            successor_id=self.successor_id,
        )

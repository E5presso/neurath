"""원문·참조·정정 관계를 프레임워크 테이블로 명시적으로 매핑한다."""

from datetime import UTC, datetime
from typing import Self, override
from uuid import UUID

from spakky.plugins.sqlalchemy.orm.table import AbstractMappableTable, Table
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from neurath.domain.aggregates.request_source import RequestSource, SourceKind


@Table(RequestSource)
class RequestSourceModel(AbstractMappableTable[RequestSource]):
    """발신 맥락과 원문의 최초 세션을 보존한다.

    Attributes:
        id: 도메인 객체의 안정적인 식별자.
        version: 프레임워크의 도메인 변경 토큰.
        created_at: 최초 생성 시각.
        updated_at: 마지막 변경 시각.
        revision: 저장소의 정수 낙관적 버전.
        project_id: 출처의 프로젝트.
        session_id: 최초 기록 세션.
        kind: 출처 용도.
        body: 보존한 원문.
        author: 제공된 발신 맥락.
        reference: 원문 참조.
        corrects_id: 정정 대상 출처.
    """

    __tablename__ = "core_request_sources"
    __table_args__ = (
        UniqueConstraint("project_id", "id", name="uq_core_source_scope"),
        ForeignKeyConstraint(
            ["project_id", "session_id"], ["core_sessions.project_id", "core_sessions.id"]
        ),
        CheckConstraint(
            "kind IN ('prompt','ticket','spec','correction','status','summary')", name="source_kind"
        ),
        CheckConstraint("revision >= 1", name="source_revision_positive"),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True)
    version: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)

    __mapper_args__ = {"version_id_col": revision}
    project_id: Mapped[str] = mapped_column(String, ForeignKey("core_projects.id"), nullable=False)
    session_id: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    body: Mapped[str] = mapped_column(String, nullable=False)
    author: Mapped[str | None] = mapped_column(String, nullable=True)
    reference: Mapped[str | None] = mapped_column(String, nullable=True)
    corrects_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("core_request_sources.id"), nullable=True
    )

    @classmethod
    @override
    def from_domain(cls, domain: RequestSource) -> Self:
        """원문과 프레임워크 메타데이터를 레코드로 복사한다.

        Args:
            domain: 저장할 출처.

        Returns:
            Self: 모든 출처 필드를 복사한 레코드.
        """
        return cls(
            id=domain.uid,
            version=domain.version,
            created_at=domain.created_at.astimezone(UTC).replace(tzinfo=None),
            updated_at=domain.updated_at.astimezone(UTC).replace(tzinfo=None),
            revision=domain.revision,
            project_id=domain.project_id,
            session_id=domain.session_id,
            kind=domain.kind.value,
            body=domain.body,
            author=domain.author,
            reference=domain.reference,
            corrects_id=domain.corrects_id,
        )

    @override
    def to_domain(self) -> RequestSource:
        """저장 수명과 독립적인 출처를 복원한다.

        Returns:
            RequestSource: 원문과 최초 맥락을 유지하는 출처.
        """
        return RequestSource(
            uid=self.id,
            version=self.version,
            created_at=self.created_at.replace(tzinfo=UTC),
            updated_at=self.updated_at.replace(tzinfo=UTC),
            revision=self.revision,
            project_id=self.project_id,
            session_id=self.session_id,
            kind=SourceKind(self.kind),
            body=self.body,
            author=self.author,
            reference=self.reference,
            corrects_id=self.corrects_id,
        )

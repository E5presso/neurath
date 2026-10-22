"""정규 작업 폴더의 현재 작성 소유자를 조회한다. 버전과 UTC 메타데이터를 명시적으로 왕복한다."""

from datetime import UTC, datetime
from typing import Self, override
from uuid import UUID

from spakky.plugins.sqlalchemy.orm.table import AbstractMappableTable, Table
from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import DateTime

from neurath.domain.aggregates.writer import Writer


@Table(Writer)
class WriterModel(AbstractMappableTable[Writer]):
    """정규 작업 폴더의 현재 작성 소유자를 조회한다.

    Attributes:
        id: 내부 aggregate 식별자.
        version: 프레임워크 변경 토큰.
        created_at: 최초 생성 시각.
        updated_at: 마지막 변경 시각.
        resource: 경쟁하는 작성이 공유하는 정규 작업 폴더.
        execution_id: 현재 작성 실행이며 해제됐으면 None.
        turn_id: 실제 호스트 턴 또는 prompt ID.
        tool_use_id: 작성 결과와 대조할 실제 도구 호출 ID.
        generation: 재취득 때 증가하는 작성 세대.
        revision: 저장 시 비교하는 낙관적 잠금 버전.
    """

    __tablename__ = "core_writers"
    __table_args__ = (UniqueConstraint("resource"),)
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

    resource: Mapped[str] = mapped_column(String, nullable=False)
    execution_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("core_executions.id"), nullable=True
    )
    turn_id: Mapped[str] = mapped_column(String, nullable=False)
    tool_use_id: Mapped[str] = mapped_column(String, nullable=False)
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)

    __mapper_args__ = {"version_id_col": revision}

    @classmethod
    @override
    def from_domain(cls, domain: Writer) -> Self:
        """도메인의 현재 상태를 저장 가능한 UTC 레코드로 복사한다.

        Args:
            domain: 저장할 Writer aggregate.

        Returns:
            Self: 현재 버전과 상태를 가진 저장 레코드.
        """
        return cls(
            id=domain.uid,
            version=domain.version,
            created_at=domain.created_at.astimezone(UTC).replace(tzinfo=None),
            updated_at=domain.updated_at.astimezone(UTC).replace(tzinfo=None),
            revision=domain.revision,
            resource=domain.resource,
            execution_id=domain.execution_id,
            turn_id=domain.turn_id,
            tool_use_id=domain.tool_use_id,
            generation=domain.generation,
        )

    @override
    def to_domain(self) -> Writer:
        """저장된 UTC 시각과 상태를 요청에 독립적인 aggregate로 복원한다.

        Returns:
            Writer: 세션을 닫은 뒤에도 읽을 수 있는 도메인 상태.
        """
        return Writer(
            uid=self.id,
            version=self.version,
            created_at=self.created_at.replace(tzinfo=UTC),
            updated_at=self.updated_at.replace(tzinfo=UTC),
            revision=self.revision,
            resource=self.resource,
            execution_id=self.execution_id,
            turn_id=self.turn_id,
            tool_use_id=self.tool_use_id,
            generation=self.generation,
        )

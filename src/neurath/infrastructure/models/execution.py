"""세션과 실제 자식 식별자로 실행 상태를 조회한다. 버전과 UTC 메타데이터를 명시적으로 왕복한다."""

from datetime import UTC, datetime
from typing import Self, override
from uuid import UUID

from spakky.plugins.sqlalchemy.orm.table import AbstractMappableTable, Table
from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import DateTime

from neurath.domain.aggregates.execution import Execution
from neurath.domain.enums.execution_pause_cause import ExecutionPauseCause
from neurath.domain.enums.execution_status import ExecutionStatus


@Table(Execution)
class ExecutionModel(AbstractMappableTable[Execution]):
    """세션과 실제 자식 식별자로 실행 상태를 조회한다.

    Attributes:
        id: 내부 aggregate 식별자.
        version: 프레임워크 변경 토큰.
        created_at: 최초 생성 시각.
        updated_at: 마지막 변경 시각.
        session_id: 실제 연결이 속한 내부 호스트 세션 ID.
        agent_id: 네이티브 자식 ID이며 루트는 빈 문자열.
        start_source: 마지막 SessionStart의 실제 원인.
        turn_id: 실제 호스트 턴 또는 prompt ID.
        status: 실행 중·대기·취소·종료 구분.
        reason: 최근 호스트 중지나 취소 사유.
        stop_snapshot: 직전 계속 피드백에 사용한 태스크 개정과 상태.
        pause_cause: 정상 대기·장애·취소 요청의 원인.
        revision: 저장 시 비교하는 낙관적 잠금 버전.
    """

    __tablename__ = "core_executions"
    __table_args__ = (UniqueConstraint("session_id", "agent_id"),)
    id: Mapped[UUID] = mapped_column(Uuid(), primary_key=True)
    version: Mapped[UUID] = mapped_column(
        Uuid(), nullable=False, server_default="00000000000000000000000000000000"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="1970-01-01 00:00:00"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="1970-01-01 00:00:00"
    )

    session_id: Mapped[UUID] = mapped_column(Uuid(), ForeignKey("core_sessions.id"), nullable=False)
    agent_id: Mapped[str] = mapped_column(String, nullable=False)
    start_source: Mapped[str] = mapped_column(String, nullable=False)
    turn_id: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    reason: Mapped[str] = mapped_column(String, nullable=False)
    stop_snapshot: Mapped[str] = mapped_column(String, nullable=False)
    pause_cause: Mapped[str | None] = mapped_column(String)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)

    __mapper_args__ = {"version_id_col": revision}

    @classmethod
    @override
    def from_domain(cls, domain: Execution) -> Self:
        """도메인의 현재 상태를 저장 가능한 UTC 레코드로 복사한다.

        Args:
            domain: 저장할 Execution aggregate.

        Returns:
            Self: 현재 버전과 상태를 가진 저장 레코드.
        """
        return cls(
            id=domain.uid,
            version=domain.version,
            created_at=domain.created_at.astimezone(UTC).replace(tzinfo=None),
            updated_at=domain.updated_at.astimezone(UTC).replace(tzinfo=None),
            revision=domain.revision,
            pause_cause=domain.pause_cause,
            session_id=domain.session_id,
            agent_id=domain.agent_id,
            start_source=domain.start_source,
            turn_id=domain.turn_id,
            status=domain.status.value,
            reason=domain.reason,
            stop_snapshot=domain.stop_snapshot,
        )

    @override
    def to_domain(self) -> Execution:
        """저장된 UTC 시각과 상태를 요청에 독립적인 aggregate로 복원한다.

        Returns:
            Execution: 세션을 닫은 뒤에도 읽을 수 있는 도메인 상태.
        """
        return Execution(
            uid=self.id,
            version=self.version,
            created_at=self.created_at.replace(tzinfo=UTC),
            updated_at=self.updated_at.replace(tzinfo=UTC),
            revision=self.revision,
            pause_cause=None if self.pause_cause is None else ExecutionPauseCause(self.pause_cause),
            session_id=self.session_id,
            agent_id=self.agent_id,
            start_source=self.start_source,
            turn_id=self.turn_id,
            status=ExecutionStatus(self.status),
            reason=self.reason,
            stop_snapshot=self.stop_snapshot,
        )

"""태스크가 소유한 감시·사건·알림을 원장과 원자적으로 저장한다."""

from typing import Self
from uuid import UUID

from spakky.plugins.sqlalchemy.orm.table import AbstractTable, Table
from sqlalchemy import JSON, Boolean, ForeignKey, ForeignKeyConstraint, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from neurath.domain.monitoring import MonitorEvent, MonitorKind, NoticeStatus, TaskMonitor


@Table()
class TaskMonitorModel(AbstractTable):
    """독립 저장소 없이 태스크의 감시 이력을 매핑한다.

    Attributes:
        task_id: 소유 태스크.
        number: 감시 순번.
        wait_number: 원 대기 순번.
        definition_number: 원 요구 개정.
        owner_execution_id: 관찰·알림 소유 실행.
        kind: 결정론적 관찰 종류.
        target: 원래 요청 대상.
        remaining_polls: 남은 관찰 예산.
        generation: 자원 소유 세대.
        active: 새 관찰·제출 허용 여부.
        initial_state: 첫 완결 관찰.
        current_state: 최신 완결 상태.
        poll_id: 종료 미확인 자원.
        error: 관찰 실패와 필요한 조작.
        stop_reason: 감시 중지 사유.
        events: 감시가 소유한 정확한 변화 사건.
    """

    __tablename__ = "core_task_monitors"
    task_id: Mapped[UUID] = mapped_column(Uuid(), ForeignKey("core_tasks.id"), primary_key=True)
    number: Mapped[int] = mapped_column(Integer, primary_key=True)
    wait_number: Mapped[int] = mapped_column(Integer, nullable=False)
    definition_number: Mapped[int] = mapped_column(Integer, nullable=False)
    owner_execution_id: Mapped[UUID] = mapped_column(
        Uuid(), ForeignKey("core_executions.id"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String, nullable=False)
    target: Mapped[str] = mapped_column(String, nullable=False)
    remaining_polls: Mapped[int] = mapped_column(Integer, nullable=False)
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    initial_state: Mapped[str | None] = mapped_column(String, nullable=True)
    current_state: Mapped[str | None] = mapped_column(String, nullable=True)
    poll_id: Mapped[UUID | None] = mapped_column(Uuid(), nullable=True)
    error: Mapped[str] = mapped_column(String, nullable=False)
    stop_reason: Mapped[str] = mapped_column(String, nullable=False)
    events: Mapped[list[MonitorEventModel]] = relationship(
        lazy="selectin", cascade="all, delete-orphan", order_by="MonitorEventModel.number"
    )

    @classmethod
    def from_value(cls, value: TaskMonitor, task_id: UUID) -> Self:
        """감시와 모든 사건을 소유 태스크에 종속시킨다.

        Args:
            value: 저장할 감시 값.
            task_id: 소유 태스크.

        Returns:
            Self: 전체 사건·예산·자원 상태를 포함한 매핑.
        """
        return cls(
            task_id=task_id,
            number=value.number,
            wait_number=value.wait_number,
            definition_number=value.definition_number,
            owner_execution_id=value.owner_execution_id,
            kind=value.kind.value,
            target=value.target,
            remaining_polls=value.remaining_polls,
            generation=value.generation,
            active=value.active,
            initial_state=value.initial_state,
            current_state=value.current_state,
            poll_id=value.poll_id,
            error=value.error,
            stop_reason=value.stop_reason,
            events=[
                MonitorEventModel.from_value(event, task_id, value.number) for event in value.events
            ],
        )

    def to_value(self) -> TaskMonitor:
        """원 감시와 사건·알림 상태를 복원한다.

        Returns:
            TaskMonitor: 별도 생명주기를 만들지 않는 태스크 자식 값.
        """
        return TaskMonitor(
            number=self.number,
            wait_number=self.wait_number,
            definition_number=self.definition_number,
            owner_execution_id=self.owner_execution_id,
            kind=MonitorKind(self.kind),
            target=self.target,
            remaining_polls=self.remaining_polls,
            generation=self.generation,
            active=self.active,
            initial_state=self.initial_state,
            current_state=self.current_state,
            poll_id=self.poll_id,
            error=self.error,
            stop_reason=self.stop_reason,
            events=tuple(event.to_value() for event in self.events),
        )


@Table()
class MonitorEventModel(AbstractTable):
    """사건 ACK와 대기 해소 및 알림 관찰을 독립적으로 보존한다.

    Attributes:
        task_id: 소유 태스크.
        monitor_number: 소유 감시 순번.
        number: 정확한 사건 순번.
        state: 완결된 변화 상태.
        reference: 실제 관찰 근거.
        body: 원 조건과 후속 범위가 담긴 알림.
        acknowledged: 정확한 사건 소비 확인.
        resolved: 이 사건으로 대기를 해소했는지 여부.
        notice_status: 작성·제출·실패·전달 상태.
        attempts: 소비한 제출 예산.
        error: 제출 실패와 필요한 조작.
        delivery_errors: 재시도 뒤에도 남기는 실제 실패 이력.
    """

    __tablename__ = "core_monitor_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["task_id", "monitor_number"],
            ["core_task_monitors.task_id", "core_task_monitors.number"],
        ),
    )
    task_id: Mapped[UUID] = mapped_column(Uuid(), primary_key=True)
    monitor_number: Mapped[int] = mapped_column(Integer, primary_key=True)
    number: Mapped[int] = mapped_column(Integer, primary_key=True)
    state: Mapped[str] = mapped_column(String, nullable=False)
    reference: Mapped[str] = mapped_column(String, nullable=False)
    body: Mapped[str] = mapped_column(String, nullable=False)
    acknowledged: Mapped[bool] = mapped_column(Boolean, nullable=False)
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False)
    notice_status: Mapped[str] = mapped_column(String, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    error: Mapped[str] = mapped_column(String, nullable=False)

    delivery_errors: Mapped[list[str]] = mapped_column(JSON, nullable=False)

    @classmethod
    def from_value(cls, value: MonitorEvent, task_id: UUID, monitor_number: int) -> Self:
        """실제 사건의 원문·소비·제출 관찰을 매핑한다.

        Args:
            value: 보존할 정확한 사건.
            task_id: 소유 태스크.
            monitor_number: 소유 감시 순번.

        Returns:
            Self: 모든 사건 상태를 포함한 자식 매핑.
        """
        return cls(
            task_id=task_id,
            monitor_number=monitor_number,
            number=value.number,
            delivery_errors=list(value.delivery_errors),
            state=value.state,
            reference=value.reference,
            body=value.body,
            acknowledged=value.acknowledged,
            resolved=value.resolved,
            notice_status=value.notice_status.value,
            attempts=value.attempts,
            error=value.error,
        )

    def to_value(self) -> MonitorEvent:
        """개별 사건의 본문과 알림 실패까지 복원한다.

        Returns:
            MonitorEvent: 정확한 사건에 연결한 보존 값.
        """
        return MonitorEvent(
            number=self.number,
            delivery_errors=tuple(self.delivery_errors),
            state=self.state,
            reference=self.reference,
            body=self.body,
            acknowledged=self.acknowledged,
            resolved=self.resolved,
            notice_status=NoticeStatus(self.notice_status),
            attempts=self.attempts,
            error=self.error,
        )

"""Delegation의 주소·범위·관찰 이력을 선언형 테이블로 보존한다."""

from datetime import UTC, datetime
from typing import Self, override
from uuid import UUID

from spakky.plugins.sqlalchemy.orm.table import AbstractMappableTable, Table
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from neurath.domain.aggregates.delegation import Delegation
from neurath.domain.delegation_records import (
    DelegationReport,
    DelegationRole,
    DelegationRoute,
    DelegationStatus,
    ProviderPlan,
)
from neurath.domain.provider import ProviderKind, ProviderStatus


@Table(Delegation)
class DelegationModel(AbstractMappableTable[Delegation]):
    """Delegation의 저장 상태와 낙관적 개정을 왕복한다.

    Attributes:
        id: 도메인의 안정적인 식별자.
        version: 프레임워크가 관리하는 변경 토큰.
        created_at: 최초 생성 UTC 시각.
        updated_at: 마지막 변경 UTC 시각.
        revision: 저장소 낙관적 버전.
        task_id: 원래 작업.
        definition_number: 맡긴 요구 개정.
        source_id: 원래 사용자 지시 또는 정정의 출처.
        parent_id: 재위임의 원 배정이며 최초 배정이면 None.
        sender_id: 배정 책임을 가진 피어.
        recipient_id: 수신 피어이며 독립 실행 준비 시 None.
        role: 수행자 또는 검토자.
        scope: 위임받은 명시적 범위.
        route: 피어·네이티브 자식·provider 경로.
        status: str,
        message_id: 배정을 전달하는 원 메시지 ID.
        execution_reference: 실제 provider 실행 또는 네이티브 작업 참조.
        progress: 수신자의 진행 관찰 이력.
        stop_reason: 부모 정정·취소로 더 실행할 수 없는 이유.
        stop_evidence: 실제 중단 관찰. 없으면 중단 미확인.
        plan_provider: 고정한 실행 공급자.
        plan_model: 실제 조회해서 선택한 구체 모델.
        plan_policy: 명시적으로 선택한 실행 권한 정책.
        plan_directory: 외부 프로세스의 작업 폴더.
        plan_parent_session_id: 배정을 시작한 Neurath 세션.
        provider_requested: 외부 실행을 요청해 커밋한 사실이며 실제 시작과 구분한다.
        provider_status: 마지막 provider 실행 관찰.
        provider_output: 실제 실행의 결과 본문.
        provider_error: 실패·미확인 관찰의 설명.
        native_session_id: str | None,
        report_summary: 수신한 수행 또는 검토 보고 원문.
        report_references: 보고가 인용한 검사·산출물 근거.
        report_remaining_work: 보고 시점에 남아 있던 작업.
    """

    __tablename__ = "core_delegations"
    __table_args__ = (
        UniqueConstraint("task_id", "definition_number", "sender_id", "role"),
        Index(
            "uq_core_root_delegation",
            "task_id",
            "definition_number",
            "role",
            unique=True,
            sqlite_where=text("parent_id IS NULL"),
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid(), primary_key=True)
    version: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    task_id: Mapped[UUID] = mapped_column(Uuid(), ForeignKey("core_tasks.id"), nullable=False)
    definition_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_id: Mapped[UUID] = mapped_column(
        Uuid(), ForeignKey("core_request_sources.id"), nullable=False
    )
    parent_id: Mapped[UUID | None] = mapped_column(
        Uuid(), ForeignKey("core_delegations.id"), nullable=True
    )
    sender_id: Mapped[UUID] = mapped_column(Uuid(), ForeignKey("core_peers.id"), nullable=False)
    recipient_id: Mapped[UUID | None] = mapped_column(
        Uuid(), ForeignKey("core_peers.id"), nullable=True
    )
    role: Mapped[str] = mapped_column(String, nullable=False)
    scope: Mapped[str] = mapped_column(String, nullable=False)
    route: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    message_id: Mapped[UUID | None] = mapped_column(
        Uuid(), ForeignKey("core_messages.id"), nullable=True
    )
    execution_reference: Mapped[str | None] = mapped_column(String, nullable=True)
    progress: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    stop_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    stop_evidence: Mapped[str | None] = mapped_column(String, nullable=True)
    plan_provider: Mapped[str | None] = mapped_column(String, nullable=True)
    plan_model: Mapped[str | None] = mapped_column(String, nullable=True)
    plan_policy: Mapped[str | None] = mapped_column(String, nullable=True)
    plan_directory: Mapped[str | None] = mapped_column(String, nullable=True)
    plan_parent_session_id: Mapped[UUID | None] = mapped_column(Uuid(), nullable=True)
    provider_requested: Mapped[bool] = mapped_column(Boolean, nullable=False)
    provider_status: Mapped[str | None] = mapped_column(String, nullable=True)
    provider_output: Mapped[str] = mapped_column(String, nullable=False)
    provider_error: Mapped[str | None] = mapped_column(String, nullable=True)
    native_session_id: Mapped[str | None] = mapped_column(String, nullable=True)
    report_summary: Mapped[str | None] = mapped_column(String, nullable=True)
    report_references: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    report_remaining_work: Mapped[str | None] = mapped_column(String, nullable=True)
    __mapper_args__ = {"version_id_col": revision}

    @classmethod
    @override
    def from_domain(cls, domain: Delegation) -> Self:
        """범위와 원문·관찰을 저장할 레코드로 변환한다.

        Args:
            domain: 저장할 Delegation.

        Returns:
            Self: 원문을 보존한 저장 레코드.
        """
        return cls(
            id=domain.uid,
            version=domain.version,
            created_at=domain.created_at.astimezone(UTC).replace(tzinfo=None),
            updated_at=domain.updated_at.astimezone(UTC).replace(tzinfo=None),
            revision=domain.revision,
            task_id=domain.task_id,
            definition_number=domain.definition_number,
            source_id=domain.source_id,
            parent_id=domain.parent_id,
            sender_id=domain.sender_id,
            recipient_id=domain.recipient_id,
            role=domain.role.value,
            scope=domain.scope,
            route=domain.route.value,
            status=domain.status.value,
            message_id=domain.message_id,
            execution_reference=domain.execution_reference,
            progress=list(domain.progress),
            stop_reason=domain.stop_reason,
            stop_evidence=domain.stop_evidence,
            plan_provider=None if domain.plan is None else domain.plan.provider,
            plan_model=None if domain.plan is None else domain.plan.model,
            plan_policy=None if domain.plan is None else domain.plan.policy,
            plan_directory=None if domain.plan is None else domain.plan.directory,
            plan_parent_session_id=None if domain.plan is None else domain.plan.parent_session_id,
            provider_requested=domain.provider_requested,
            provider_status=domain.provider_status,
            provider_output=domain.provider_output,
            provider_error=domain.provider_error,
            native_session_id=domain.native_session_id,
            report_summary=None if domain.report is None else domain.report.summary,
            report_references=[] if domain.report is None else list(domain.report.references),
            report_remaining_work=None if domain.report is None else domain.report.remaining_work,
        )

    @override
    def to_domain(self) -> Delegation:
        """저장된 원문·관찰을 요청과 독립적인 도메인 객체로 복원한다.

        Returns:
            Delegation: 저장된 현재 상태와 과거 관찰.
        """
        return Delegation(
            uid=self.id,
            version=self.version,
            created_at=self.created_at.replace(tzinfo=UTC),
            updated_at=self.updated_at.replace(tzinfo=UTC),
            revision=self.revision,
            task_id=self.task_id,
            definition_number=self.definition_number,
            source_id=self.source_id,
            parent_id=self.parent_id,
            sender_id=self.sender_id,
            recipient_id=self.recipient_id,
            role=DelegationRole(self.role),
            scope=self.scope,
            route=DelegationRoute(self.route),
            status=DelegationStatus(self.status),
            message_id=self.message_id,
            execution_reference=self.execution_reference,
            progress=self.progress,
            stop_reason=self.stop_reason,
            stop_evidence=self.stop_evidence,
            provider_requested=self.provider_requested,
            provider_status=None
            if self.provider_status is None
            else ProviderStatus(self.provider_status),
            provider_output=self.provider_output,
            provider_error=self.provider_error,
            native_session_id=self.native_session_id,
            plan=self._provider_plan(),
            report=None
            if self.report_summary is None
            else DelegationReport(
                summary=self.report_summary,
                references=self.report_references,
                remaining_work=self.report_remaining_work,
            ),
        )

    def _provider_plan(self) -> ProviderPlan | None:
        """계획이 있으면 필수 부모 참조를 확인하고 원 설정으로 복원한다.

        Returns:
            ProviderPlan | None: 보존한 실행 계획이며 피어 배정이면 None.

        Raises:
            ValueError: 저장된 계획에 필수 부모 세션이 빠져 있는 경우.
        """
        if self.plan_provider is None:
            return None
        if self.plan_parent_session_id is None:
            raise ValueError("Stored provider plan has no parent session")
        return ProviderPlan(
            provider=ProviderKind(self.plan_provider),
            model=self.plan_model or "",
            policy=self.plan_policy or "",
            directory=self.plan_directory or "",
            parent_session_id=self.plan_parent_session_id,
        )

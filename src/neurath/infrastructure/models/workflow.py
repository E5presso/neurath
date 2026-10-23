"""워크플로의 정의 개정·단계·시도를 선언형 소유 관계로 매핑한다."""

from datetime import UTC, datetime
from typing import Self, override
from uuid import UUID

from spakky.plugins.sqlalchemy.orm.table import AbstractMappableTable, AbstractTable, Table
from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from neurath.domain.aggregates.workflow import WorkflowRun
from neurath.domain.workflow_records import (
    PhaseAttempt,
    PhaseDefinition,
    PhaseResult,
    PhaseStatus,
    WorkflowDefinition,
    WorkflowRevision,
)


@Table(WorkflowRun)
class WorkflowModel(AbstractMappableTable[WorkflowRun]):
    """선택 절차의 개정과 실행 시도를 한 run의 소유 관계로 저장한다.

    Attributes:
        id: run의 안정적인 식별자.
        version: 프레임워크가 관리하는 도메인 변경 토큰.
        created_at: run을 처음 생성한 UTC 시각.
        updated_at: 마지막 상태 변경의 UTC 시각.
        revision: 저장소의 낙관적 잠금 버전.
        project_id: 연결 태스크의 프로젝트 ID.
        session_id: run을 소유한 세션 ID.
        task_id: 이 절차로 수행하는 태스크 ID.
        revisions: 이전 정의도 함께 보존하는 개정 목록.
        attempts: 실행·결과·생략 시도 목록.
    """

    __tablename__ = "core_workflows"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "task_id"], ["core_tasks.project_id", "core_tasks.id"]),
        ForeignKeyConstraint(
            ["project_id", "session_id"], ["core_sessions.project_id", "core_sessions.id"]
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid(), primary_key=True)
    version: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    project_id: Mapped[UUID] = mapped_column(Uuid(), ForeignKey("core_projects.id"), nullable=False)
    session_id: Mapped[UUID] = mapped_column(Uuid(), ForeignKey("core_sessions.id"), nullable=False)
    task_id: Mapped[UUID] = mapped_column(
        Uuid(), ForeignKey("core_tasks.id"), unique=True, nullable=False
    )

    __mapper_args__ = {"version_id_col": revision}
    revisions: Mapped[list[WorkflowRevisionModel]] = relationship(
        lazy="selectin", cascade="all, delete-orphan", order_by="WorkflowRevisionModel.number"
    )
    attempts: Mapped[list[PhaseAttemptModel]] = relationship(
        lazy="selectin", cascade="all, delete-orphan", order_by="PhaseAttemptModel.number"
    )

    @classmethod
    @override
    def from_domain(cls, domain: WorkflowRun) -> Self:
        """run의 모든 정의 개정과 시도를 ORM 객체로 복사한다.

        Args:
            domain: 저장할 run과 소유 이력.

        Returns:
            Self: UTC 기준 시각과 자식 관계를 가진 저장 객체.
        """
        return cls(
            id=domain.uid,
            version=domain.version,
            created_at=domain.created_at.astimezone(UTC).replace(tzinfo=None),
            updated_at=domain.updated_at.astimezone(UTC).replace(tzinfo=None),
            revision=domain.revision,
            project_id=domain.project_id,
            session_id=domain.session_id,
            task_id=domain.task_id,
            revisions=[
                WorkflowRevisionModel.from_value(value, domain.uid, number)
                for number, value in enumerate(domain.revisions, 1)
            ],
            attempts=[PhaseAttemptModel.from_value(value, domain.uid) for value in domain.attempts],
        )

    @override
    def to_domain(self) -> WorkflowRun:
        """시각의 UTC와 정의·시도 순서를 복원한 도메인 run을 만든다.

        Returns:
            WorkflowRun: ORM 수명과 분리된 현재 상태 및 소유 이력.
        """
        return WorkflowRun(
            uid=self.id,
            version=self.version,
            created_at=self.created_at.replace(tzinfo=UTC),
            updated_at=self.updated_at.replace(tzinfo=UTC),
            revision=self.revision,
            project_id=self.project_id,
            session_id=self.session_id,
            task_id=self.task_id,
            revisions=tuple(value.to_value() for value in self.revisions),
            attempts=tuple(value.to_value() for value in self.attempts),
        )


@Table()
class WorkflowRevisionModel(AbstractTable):
    """이전 절차를 덮어쓰지 않고 태스크 요구에 연결한 정의 개정을 저장한다.

    Attributes:
        run_id: 정의를 소유한 run ID.
        number: run 안에서 증가하는 정의 개정 번호.
        skill: 선택한 스킬 이름.
        definition_version: 선택한 스킬 정의의 버전.
        inputs: 이 정의를 선택할 때 고정한 입력 값.
        task_definition_number: 같은 시점의 태스크 요구 개정.
        reason: 시작 또는 정의를 수정한 이유.
        phases: 이 개정에 고정한 순서 있는 단계 정의.
    """

    __tablename__ = "core_workflow_revisions"
    run_id: Mapped[UUID] = mapped_column(Uuid(), ForeignKey("core_workflows.id"), primary_key=True)
    number: Mapped[int] = mapped_column(Integer, primary_key=True)
    skill: Mapped[str] = mapped_column(String, nullable=False)
    definition_version: Mapped[str] = mapped_column(String, nullable=False)
    inputs: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False)
    task_definition_number: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String, nullable=False)

    phases: Mapped[list[PhaseDefinitionModel]] = relationship(
        lazy="selectin", cascade="all, delete-orphan", order_by="PhaseDefinitionModel.position"
    )

    @classmethod
    def from_value(cls, value: WorkflowRevision, run_id: UUID, number: int) -> Self:
        """선택한 스킬 정의와 단계들을 한 개정의 자식 관계로 복사한다.

        Args:
            value: 보존할 절차 개정.
            run_id: 이 개정을 소유한 run ID.
            number: run 안의 정의 개정 번호.

        Returns:
            Self: 입력 값과 순서 있는 단계들을 가진 개정 객체.
        """
        return cls(
            run_id=run_id,
            number=number,
            skill=value.definition.skill,
            definition_version=value.definition.version,
            inputs=dict(value.definition.inputs),
            task_definition_number=value.task_definition_number,
            reason=value.reason,
            phases=[
                PhaseDefinitionModel.from_value(phase, run_id, number, index)
                for index, phase in enumerate(value.definition.phases)
            ],
        )

    def to_value(self) -> WorkflowRevision:
        """정의 버전·입력·단계와 연결된 태스크 요구 개정을 복원한다.

        Returns:
            WorkflowRevision: 개정 당시의 정의와 수정 이유.
        """
        return WorkflowRevision(
            definition=WorkflowDefinition(
                skill=self.skill,
                version=self.definition_version,
                inputs=tuple(self.inputs.items()),
                phases=tuple(phase.to_value() for phase in self.phases),
            ),
            task_definition_number=self.task_definition_number,
            reason=self.reason,
        )


@Table()
class PhaseDefinitionModel(AbstractTable):
    """절차 개정에 속한 단계의 순서·명령·검증 조건을 고정한다.

    Attributes:
        run_id: 이 정의를 소유한 run ID.
        definition_number: 소유한 절차의 개정 번호.
        position: 이 정의 안의 실행 순서.
        key: 정의 변경 사이에서 단계를 식별하는 키.
        purpose: 단계에서 달성할 결과.
        arguments: 셸 해석 없이 실행할 인자 목록.
        directory: 명령의 작업 디렉터리.
        target_revision: 실행과 검증의 대상 개정.
        checks: 성공에 필요한 검사 이름.
        skip_condition: 선택 단계의 생략 조건. 필수 단계이면 None.
        timeout: 실행 제한 시간(초).
        output_limit: 보존할 출력 바이트 한도.
        max_attempts: 실제 실행 시도의 최대 횟수.
    """

    __tablename__ = "core_workflow_phases"
    __table_args__ = (
        ForeignKeyConstraint(
            ["run_id", "definition_number"],
            ["core_workflow_revisions.run_id", "core_workflow_revisions.number"],
        ),
    )
    run_id: Mapped[UUID] = mapped_column(Uuid(), primary_key=True)
    definition_number: Mapped[int] = mapped_column(Integer, primary_key=True)
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String, nullable=False)
    purpose: Mapped[str] = mapped_column(String, nullable=False)
    arguments: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    directory: Mapped[str] = mapped_column(String, nullable=False)
    target_revision: Mapped[str] = mapped_column(String, nullable=False)
    checks: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    skip_condition: Mapped[str | None] = mapped_column(String, nullable=True)
    timeout: Mapped[float] = mapped_column(Float, nullable=False)
    output_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)

    @classmethod
    def from_value(
        cls, value: PhaseDefinition, run_id: UUID, definition_number: int, position: int
    ) -> Self:
        """단계의 명령·조건·한도를 지정한 정의 개정의 위치에 매핑한다.

        Args:
            value: 실행할 단계의 정의.
            run_id: 소유 run ID.
            definition_number: 소유 정의 개정.
            position: 해당 정의에서 실행할 순서.

        Returns:
            Self: 실행 순서와 검증 대상을 고정한 단계 객체.
        """
        return cls(
            run_id=run_id,
            definition_number=definition_number,
            position=position,
            key=value.key,
            purpose=value.purpose,
            arguments=list(value.arguments),
            directory=value.directory,
            target_revision=value.target_revision,
            checks=list(value.checks),
            skip_condition=value.skip_condition,
            timeout=value.timeout,
            output_limit=value.output_limit,
            max_attempts=value.max_attempts,
        )

    def to_value(self) -> PhaseDefinition:
        """JSON 목록을 tuple로 분리하여 단계 정의를 복원한다.

        Returns:
            PhaseDefinition: 명령·대상·검사·한도가 유지된 단계 값.
        """
        return PhaseDefinition(
            key=self.key,
            purpose=self.purpose,
            arguments=tuple(self.arguments),
            directory=self.directory,
            target_revision=self.target_revision,
            checks=tuple(self.checks),
            skip_condition=self.skip_condition,
            timeout=self.timeout,
            output_limit=self.output_limit,
            max_attempts=self.max_attempts,
        )


@Table()
class PhaseAttemptModel(AbstractTable):
    """결과 불명과 확정 결과를 같은 시도에 연결하며 늦은 결과도 보존한다.

    Attributes:
        run_id: 시도를 소유하는 run ID.
        number: run 안에서 증가하는 시도 번호.
        definition_number: 예약 시 고정한 정의 개정.
        phase_key: 실행할 단계의 키.
        status: 예약·대기·성공·실패·생략 상태.
        skip_reason: 생략 조건을 충족한다는 근거.
        result_target: 결과가 관찰한 대상 개정. 결과 전에는 None.
        summary: 관찰 결과 설명. 예약 또는 생략만 했으면 None.
        evidence: 명령·검토·산출물 근거 참조.
        checks: 실제로 충족한 검사 이름.
        output: 한도 안에서 보존한 출력.
        exit_code: 관찰한 종료 코드. 미확인이면 None.
    """

    __tablename__ = "core_workflow_attempts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["run_id", "definition_number"],
            ["core_workflow_revisions.run_id", "core_workflow_revisions.number"],
        ),
    )
    run_id: Mapped[UUID] = mapped_column(Uuid(), ForeignKey("core_workflows.id"), primary_key=True)
    number: Mapped[int] = mapped_column(Integer, primary_key=True)
    definition_number: Mapped[int] = mapped_column(Integer, nullable=False)
    phase_key: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    skip_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    result_target: Mapped[str | None] = mapped_column(String, nullable=True)
    summary: Mapped[str | None] = mapped_column(String, nullable=True)
    evidence: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    checks: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    output: Mapped[str] = mapped_column(String, nullable=False)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)

    @classmethod
    def from_value(cls, value: PhaseAttempt, run_id: UUID) -> Self:
        """예약·생략과 실제 관찰 결과의 유무를 구분하여 시도를 매핑한다.

        Args:
            value: 보존할 실행 시도.
            run_id: 시도를 소유하는 run ID.

        Returns:
            Self: 상태와 선택적인 관찰 결과를 가진 시도 객체.
        """
        result = value.result
        return cls(
            run_id=run_id,
            number=value.number,
            definition_number=value.definition_number,
            phase_key=value.phase_key,
            status=value.status.value,
            skip_reason=value.skip_reason,
            result_target=None if result is None else result.target_revision,
            summary=None if result is None else result.summary,
            evidence=[] if result is None else list(result.evidence),
            checks=[] if result is None else list(result.checks),
            output="" if result is None else result.output,
            exit_code=None if result is None else result.exit_code,
        )

    def to_value(self) -> PhaseAttempt:
        """미확정 시도와 관찰 결과를 구분해 도메인 이력을 복원한다.

        Returns:
            PhaseAttempt: 원래 정의 개정에 연결된 실행·생략·결과 기록.
        """
        result = None
        if self.result_target is not None and self.summary is not None:
            result = PhaseResult(
                status=PhaseStatus(self.status),
                target_revision=self.result_target,
                summary=self.summary,
                evidence=tuple(self.evidence),
                checks=tuple(self.checks),
                output=self.output,
                exit_code=self.exit_code,
            )
        return PhaseAttempt(
            number=self.number,
            definition_number=self.definition_number,
            phase_key=self.phase_key,
            status=PhaseStatus(self.status),
            result=result,
            skip_reason=self.skip_reason,
        )

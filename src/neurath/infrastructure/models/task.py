"""태스크와 소유한 정의·시도·대기 기록을 관계로 함께 매핑한다."""

from datetime import UTC, datetime
from typing import Self, override
from uuid import UUID

from spakky.plugins.sqlalchemy.orm.table import AbstractMappableTable, AbstractTable, Table
from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from neurath.domain.aggregates.task import Task
from neurath.domain.task_records import (
    ExternalWait,
    Outcome,
    SubmittedResult,
    TaskAttempt,
    TaskDefinition,
    TaskResult,
    TaskStatus,
)
from neurath.infrastructure.uuid_type import UUIDText


@Table(Task)
class TaskModel(AbstractMappableTable[Task]):
    """태스크 도메인 객체 전체를 기본 저장소가 병합할 수 있게 변환한다.

    Attributes:
        id: 도메인 객체의 안정적인 식별자.
        version: 프레임워크의 도메인 변경 토큰.
        created_at: 최초 생성 시각.
        updated_at: 마지막 변경 시각.
        revision: 저장소의 정수 낙관적 버전.
        project_id: 작업의 프로젝트.
        owner_session_id: 작업 소유 세션.
        status: 현재 작업 상태.
        current_attempt_number: 현재 요구의 시도 번호.
        follow_up_of: 원래 미달 요구의 작업.
        invalidated_reason: 무효화 이유.
        definitions: 소유한 요구 개정.
        attempts: 소유한 실행 시도.
        waits: 소유한 외부 대기 기록.
    """

    __tablename__ = "core_tasks"
    __table_args__ = (
        UniqueConstraint("project_id", "id", name="uq_core_task_scope"),
        ForeignKeyConstraint(
            ["project_id", "owner_session_id"], ["core_sessions.project_id", "core_sessions.id"]
        ),
        CheckConstraint(
            "status IN ('pending','active','waiting','succeeded','failed','invalidated')",
            name="task_status",
        ),
        CheckConstraint("revision >= 1", name="task_revision_positive"),
    )
    id: Mapped[UUID] = mapped_column(UUIDText, primary_key=True)
    version: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)

    __mapper_args__ = {"version_id_col": revision}
    project_id: Mapped[UUID] = mapped_column(
        UUIDText, ForeignKey("core_projects.id"), nullable=False
    )
    owner_session_id: Mapped[UUID] = mapped_column(UUIDText, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    current_attempt_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    follow_up_of: Mapped[UUID | None] = mapped_column(
        UUIDText, ForeignKey("core_tasks.id"), nullable=True
    )
    invalidated_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    definitions: Mapped[list[TaskDefinitionModel]] = relationship(
        lazy="selectin", cascade="all, delete-orphan", order_by="TaskDefinitionModel.number"
    )
    attempts: Mapped[list[TaskAttemptModel]] = relationship(
        lazy="selectin", cascade="all, delete-orphan", order_by="TaskAttemptModel.number"
    )
    waits: Mapped[list[TaskWaitModel]] = relationship(
        lazy="selectin", cascade="all, delete-orphan", order_by="TaskWaitModel.number"
    )

    @classmethod
    @override
    def from_domain(cls, domain: Task) -> Self:
        """태스크와 소유 기록 전체를 명시적으로 매핑한다.

        Args:
            domain: 저장할 태스크 도메인 객체.

        Returns:
            Self: 소유 관계까지 포함한 레코드.
        """
        return cls(
            id=domain.uid,
            version=domain.version,
            created_at=domain.created_at.astimezone(UTC).replace(tzinfo=None),
            updated_at=domain.updated_at.astimezone(UTC).replace(tzinfo=None),
            revision=domain.revision,
            project_id=domain.project_id,
            owner_session_id=domain.owner_session_id,
            status=domain.status.value,
            current_attempt_number=domain.current_attempt_number,
            follow_up_of=domain.follow_up_of,
            invalidated_reason=domain.invalidated_reason,
            definitions=[
                TaskDefinitionModel.from_value(value, domain.uid, domain.project_id)
                for value in domain.definitions
            ],
            attempts=[TaskAttemptModel.from_value(value, domain.uid) for value in domain.attempts],
            waits=[
                TaskWaitModel.from_value(value, domain.uid, number)
                for number, value in enumerate(domain.waits, start=1)
            ],
        )

    @override
    def to_domain(self) -> Task:
        """현재 상태와 전체 소유 이력을 분리된 도메인으로 복원한다.

        Returns:
            Task: 원문 개정·시도·대기를 포함한 태스크.
        """
        return Task(
            uid=self.id,
            version=self.version,
            created_at=self.created_at.replace(tzinfo=UTC),
            updated_at=self.updated_at.replace(tzinfo=UTC),
            revision=self.revision,
            project_id=self.project_id,
            owner_session_id=self.owner_session_id,
            status=TaskStatus(self.status),
            current_attempt_number=self.current_attempt_number,
            follow_up_of=self.follow_up_of,
            invalidated_reason=self.invalidated_reason,
            definitions=tuple(value.to_value() for value in self.definitions),
            attempts=tuple(value.to_value() for value in self.attempts),
            waits=tuple(value.to_value() for value in self.waits),
        )


@Table()
class TaskDefinitionModel(AbstractTable):
    """원문 개정과 그때의 의존 관계를 태스크에 종속시킨다.

    Attributes:
        task_id: 소유 태스크.
        number: 요구 개정 번호.
        project_id: 출처와 의존의 프로젝트 범위.
        source_id: 이 개정의 원문.
        title: 작업 제목.
        required_result: 달성할 결과.
        dependencies: 이 개정의 선행 작업들.
    """

    __tablename__ = "core_task_definitions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "source_id"],
            ["core_request_sources.project_id", "core_request_sources.id"],
        ),
    )
    task_id: Mapped[UUID] = mapped_column(UUIDText, ForeignKey("core_tasks.id"), primary_key=True)
    number: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[UUID] = mapped_column(UUIDText, nullable=False)
    source_id: Mapped[UUID] = mapped_column(UUIDText, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    required_result: Mapped[str] = mapped_column(String, nullable=False)
    dependencies: Mapped[list[TaskDependencyModel]] = relationship(
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="TaskDependencyModel.prerequisite_id",
    )

    @classmethod
    def from_value(cls, value: TaskDefinition, task_id: UUID, project_id: UUID) -> Self:
        """요구 개정과 선행 작업 ID들을 태스크에 종속된 ORM 객체로 변환한다.

        Args:
            value: 불변 요구 개정.
            task_id: 소유 태스크.
            project_id: 같은 프로젝트의 출처·의존 범위.

        Returns:
            Self: 요구와 의존을 포함하는 자식 레코드.
        """
        return cls(
            task_id=task_id,
            number=value.number,
            project_id=project_id,
            source_id=value.source_id,
            title=value.title,
            required_result=value.required_result,
            dependencies=[
                TaskDependencyModel(
                    task_id=task_id,
                    definition_number=value.number,
                    project_id=project_id,
                    prerequisite_id=uid,
                )
                for uid in value.dependencies
            ],
        )

    def to_value(self) -> TaskDefinition:
        """저장한 요구 개정을 복원한다.

        Returns:
            TaskDefinition: 당시 원문·목표·의존을 유지하는 개정.
        """
        return TaskDefinition(
            number=self.number,
            source_id=self.source_id,
            title=self.title,
            required_result=self.required_result,
            dependencies=tuple(item.prerequisite_id for item in self.dependencies),
        )


@Table()
class TaskDependencyModel(AbstractTable):
    """특정 요구 개정의 같은 프로젝트 선행 작업을 참조한다.

    Attributes:
        task_id: 소유 태스크.
        definition_number: 요구 개정.
        prerequisite_id: 선행 태스크.
        project_id: 두 작업의 프로젝트 범위.
    """

    __tablename__ = "core_task_dependencies"
    __table_args__ = (
        ForeignKeyConstraint(
            ["task_id", "definition_number"],
            ["core_task_definitions.task_id", "core_task_definitions.number"],
        ),
        ForeignKeyConstraint(
            ["project_id", "prerequisite_id"], ["core_tasks.project_id", "core_tasks.id"]
        ),
        CheckConstraint("task_id != prerequisite_id", name="task_not_self_dependent"),
    )
    task_id: Mapped[UUID] = mapped_column(UUIDText, primary_key=True)
    definition_number: Mapped[int] = mapped_column(Integer, primary_key=True)
    prerequisite_id: Mapped[UUID] = mapped_column(UUIDText, primary_key=True)
    project_id: Mapped[UUID] = mapped_column(UUIDText, nullable=False)


@Table()
class TaskAttemptModel(AbstractTable):
    """제출과 확정 결과를 구분하고 늦은 결과까지 시도에 보존한다.

    Attributes:
        task_id: 소유 태스크.
        number: 시도 번호.
        definition_number: 시작할 때 고정한 요구 개정.
        session_id: 시도를 시작한 세션.
        submission_summary: 후보 설명이며 미제출이면 None.
        submission_references: 후보 자료 참조.
        outcome: 실제 결과 구분이며 미확정이면 None.
        summary: 확정 결과 설명.
        observations: 실제 관찰 참조.
        remaining_work: 여전히 남은 일.
        exit_code: 관찰한 명령 종료 코드.
    """

    __tablename__ = "core_task_attempts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["task_id", "definition_number"],
            ["core_task_definitions.task_id", "core_task_definitions.number"],
        ),
    )
    task_id: Mapped[UUID] = mapped_column(UUIDText, ForeignKey("core_tasks.id"), primary_key=True)
    number: Mapped[int] = mapped_column(Integer, primary_key=True)
    definition_number: Mapped[int] = mapped_column(Integer, nullable=False)
    session_id: Mapped[UUID] = mapped_column(
        UUIDText, ForeignKey("core_sessions.id"), nullable=False
    )
    submission_summary: Mapped[str | None] = mapped_column(String, nullable=True)
    submission_references: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    outcome: Mapped[str | None] = mapped_column(String, nullable=True)
    summary: Mapped[str] = mapped_column(String, nullable=False)
    observations: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    remaining_work: Mapped[str | None] = mapped_column(String, nullable=True)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)

    @classmethod
    def from_value(cls, value: TaskAttempt, task_id: UUID) -> Self:
        """후보·확정 결과의 유무를 별도 nullable 필드로 표현한 시도 객체를 만든다.

        Args:
            value: 불변 실행 시도 기록.
            task_id: 소유 태스크.

        Returns:
            Self: 제출·확정 구분을 유지하는 자식 레코드.
        """
        submission = value.submission
        result = value.result
        return cls(
            task_id=task_id,
            number=value.number,
            definition_number=value.definition_number,
            session_id=value.session_id,
            submission_summary=None if submission is None else submission.summary,
            submission_references=[] if submission is None else list(submission.references),
            outcome=None if result is None else result.outcome.value,
            summary="" if result is None else result.summary,
            observations=[] if result is None else list(result.observations),
            remaining_work=None if result is None else result.remaining_work,
            exit_code=None if result is None else result.exit_code,
        )

    def to_value(self) -> TaskAttempt:
        """후보 설명과 outcome의 None 여부로 제출·결과의 존재를 복원한다.

        미확정 결과의 빈 summary·observations는 결과 객체로 만들지 않는다.
        참조 목록은 tuple로 복사하여 ORM의 JSON 목록과 분리한다.

        Returns:
            TaskAttempt: 원래 개정과 후보·관찰 결과.
        """
        submission = None
        if self.submission_summary is not None:
            submission = SubmittedResult(
                summary=self.submission_summary, references=tuple(self.submission_references)
            )
        result = None
        if self.outcome is not None:
            result = TaskResult(
                outcome=Outcome(self.outcome),
                summary=self.summary,
                observations=tuple(self.observations),
                remaining_work=self.remaining_work,
                exit_code=self.exit_code,
            )
        return TaskAttempt(
            number=self.number,
            definition_number=self.definition_number,
            session_id=self.session_id,
            submission=submission,
            result=result,
        )


@Table()
class TaskWaitModel(AbstractTable):
    """대기와 재개 관찰을 같은 태스크의 이력으로 저장한다.

    Attributes:
        task_id: 소유 태스크.
        number: 대기 순서.
        target: 외부 대상.
        condition: 해소 조건.
        resume_scope: 허용된 후속 범위.
        observation: 대기의 관찰 근거.
        resolution: 재개 관찰.
    """

    __tablename__ = "core_task_waits"
    task_id: Mapped[UUID] = mapped_column(UUIDText, ForeignKey("core_tasks.id"), primary_key=True)
    number: Mapped[int] = mapped_column(Integer, primary_key=True)
    target: Mapped[str] = mapped_column(String, nullable=False)
    condition: Mapped[str] = mapped_column(String, nullable=False)
    resume_scope: Mapped[str] = mapped_column(String, nullable=False)
    observation: Mapped[str] = mapped_column(String, nullable=False)
    resolution: Mapped[str | None] = mapped_column(String, nullable=True)

    @classmethod
    def from_value(cls, value: ExternalWait, task_id: UUID, number: int) -> Self:
        """대기와 해소 관찰을 명시적으로 매핑한다.

        Args:
            value: 보존할 외부 대기.
            task_id: 소유 태스크.
            number: 태스크 안의 대기 순서.

        Returns:
            Self: 복원 가능한 대기 레코드.
        """
        return cls(
            task_id=task_id,
            number=number,
            target=value.target,
            condition=value.condition,
            resume_scope=value.resume_scope,
            observation=value.observation,
            resolution=value.resolution,
        )

    def to_value(self) -> ExternalWait:
        """저장된 외부 대기와 선택적인 해소 관찰을 불변 값으로 복원한다.

        Returns:
            ExternalWait: 외부 의존과 해소 관찰.
        """
        return ExternalWait(
            target=self.target,
            condition=self.condition,
            resume_scope=self.resume_scope,
            observation=self.observation,
            resolution=self.resolution,
        )

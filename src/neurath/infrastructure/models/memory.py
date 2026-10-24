"""출처 있는 기억 본문을 현재 enclave와 별도 테이블에 보존한다."""

from datetime import UTC, datetime
from typing import Self, TypedDict, override
from uuid import UUID

from spakky.plugins.sqlalchemy.orm.table import AbstractMappableTable, Table
from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from neurath.domain.aggregates.memory import Memory, MemoryKind
from neurath.domain.values.lesson_observation import LessonObservation, LessonState


class LessonData(TypedDict):
    """교훈 관찰의 JSON 저장 구조다.

    Attributes:
        state: 현재 적용 상태.
        reason: 효과 또는 보류·철회 이유.
        references: 관찰 근거.
        failure_case: 실패 사례 확인 근거.
        normal_case: 정상 대조 확인 근거.
        effective: 실제 효과이며 미확인은 None.
    """

    state: str
    reason: str
    references: list[str]
    failure_case: str
    normal_case: str
    effective: bool | None


@Table(Memory)
class MemoryModel(AbstractMappableTable[Memory]):
    """선택 조회할 원래 본문·종류·관련 범위·출처를 매핑한다.

    Attributes:
        id: 저장된 aggregate의 식별자.
        version: 프레임워크 변경 토큰.
        created_at: 최초 기록의 UTC 시각.
        updated_at: 마지막 변경의 UTC 시각.
        project_id: 소속 프로젝트의 외래 키.
        session_id: 현재 맥락 또는 원래 기억 작성 세션.
        task_id: 관련 작업의 선택적 외래 키.
        kind: 기억 또는 사실의 종류.
        content: 자르지 않고 보존한 전체 본문.
        references: 원문·산출물·상세 자료의 참조 목록.
        graph_directory: 커밋된 외부 갱신 요청의 경로.
        graph_reference: 저장된 갱신 성공 참조.
        graph_error: 저장된 갱신 실패 관찰.
        lessons: 교훈의 적용·보류·효과 관찰 이력.
        revision: 동시 변경을 거절하는 낙관적 저장 버전.
    """

    __tablename__ = "core_memories"
    id: Mapped[UUID] = mapped_column(Uuid(), primary_key=True)
    version: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    project_id: Mapped[UUID] = mapped_column(Uuid(), ForeignKey("core_projects.id"), nullable=False)
    session_id: Mapped[UUID] = mapped_column(Uuid(), ForeignKey("core_sessions.id"), nullable=False)
    task_id: Mapped[UUID | None] = mapped_column(Uuid(), ForeignKey("core_tasks.id"))
    kind: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(String, nullable=False)
    references: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    graph_directory: Mapped[str | None] = mapped_column(String)
    graph_reference: Mapped[str | None] = mapped_column(String)
    graph_error: Mapped[str | None] = mapped_column(String)
    lessons: Mapped[list[LessonData]] = mapped_column(JSON, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    __mapper_args__ = {"version_id_col": revision}

    @classmethod
    @override
    def from_domain(cls, domain: Memory) -> Self:
        """보고의 원문과 참조를 손실 없이 저장 레코드로 변환한다.

        Args:
            domain: 저장할 기억 기록.

        Returns:
            Self: 본문과 원래 소유 범위가 유지된 레코드.
        """
        return cls(
            id=domain.uid,
            version=domain.version,
            created_at=domain.created_at.astimezone(UTC).replace(tzinfo=None),
            updated_at=domain.updated_at.astimezone(UTC).replace(tzinfo=None),
            project_id=domain.project_id,
            session_id=domain.session_id,
            task_id=domain.task_id,
            kind=domain.kind.value,
            content=domain.content,
            references=list(domain.references),
            graph_directory=domain.graph_directory,
            graph_reference=domain.graph_reference,
            graph_error=domain.graph_error,
            revision=domain.revision,
            lessons=[
                {
                    "state": item.state.value,
                    "reason": item.reason,
                    "references": list(item.references),
                    "failure_case": item.failure_case,
                    "normal_case": item.normal_case,
                    "effective": item.effective,
                }
                for item in domain.lessons
            ],
        )

    @override
    def to_domain(self) -> Memory:
        """기억 본문과 UTC 시각을 원래 도메인 기록으로 복원한다.

        Returns:
            Memory: 현재 사실로 승격하지 않은 과거 자료.
        """
        return Memory(
            uid=self.id,
            version=self.version,
            created_at=self.created_at.replace(tzinfo=UTC),
            updated_at=self.updated_at.replace(tzinfo=UTC),
            project_id=self.project_id,
            session_id=self.session_id,
            task_id=self.task_id,
            kind=MemoryKind(self.kind),
            content=self.content,
            references=self.references,
            graph_directory=self.graph_directory,
            graph_reference=self.graph_reference,
            graph_error=self.graph_error,
            revision=self.revision,
            lessons=tuple(
                LessonObservation(
                    state=LessonState(item["state"]),
                    reason=item["reason"],
                    references=tuple(item["references"]),
                    failure_case=item["failure_case"],
                    normal_case=item["normal_case"],
                    effective=item["effective"],
                )
                for item in self.lessons
            ),
        )

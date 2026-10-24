"""장애와 순서 있는 확인 근거를 별도 관계로 보존한다."""

from datetime import UTC, datetime
from typing import Self, override
from uuid import UUID

from spakky.plugins.sqlalchemy.orm.table import AbstractMappableTable, AbstractTable, Table
from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from neurath.domain.aggregates.incident import Incident
from neurath.domain.enums.incident_evidence_kind import IncidentEvidenceKind
from neurath.domain.enums.incident_status import IncidentStatus
from neurath.domain.values.incident_evidence import IncidentEvidence


@Table(Incident)
class IncidentModel(AbstractMappableTable[Incident]):
    """원 증상·관련 프로젝트와 해결 상태를 낙관적 개정으로 저장한다.

    Attributes:
        id: 장애 aggregate의 UUID 식별자.
        version: 프레임워크 변경 토큰.
        created_at: 최초 생성의 UTC 시각.
        updated_at: 마지막 변경의 UTC 시각.
        project_id: 관련 프로젝트의 외래 키이며 전역 장애는 None.
        symptom: 처음 관찰한 증상 원문.
        references: 원문과 실행 결과로 돌아갈 출처 목록.
        status: 미해결·이관·대체·해결의 실제 상태.
        transfers: 이관 대상과 사유의 누적 이력.
        replacement_id: 원 장애를 대체하는 같은 범위의 실제 사건 ID.
        resolution: 해결을 결정한 설명.
        revision: 호출자가 조회한 낙관적 개정.
        evidence: 순서를 보존한 재현·수정·회귀 근거.
    """

    __tablename__ = "core_incidents"
    id: Mapped[UUID] = mapped_column(Uuid(), primary_key=True)
    version: Mapped[UUID] = mapped_column(Uuid(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    project_id: Mapped[UUID | None] = mapped_column(Uuid(), ForeignKey("core_projects.id"))
    symptom: Mapped[str] = mapped_column(String, nullable=False)
    references: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    transfers: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    replacement_id: Mapped[UUID | None] = mapped_column(Uuid(), ForeignKey("core_incidents.id"))
    resolution: Mapped[str] = mapped_column(String, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence: Mapped[list[IncidentEvidenceModel]] = relationship(
        lazy="selectin", cascade="all, delete-orphan", order_by="IncidentEvidenceModel.number"
    )
    __mapper_args__ = {"version_id_col": revision}

    @classmethod
    @override
    def from_domain(cls, domain: Incident) -> Self:
        """증상과 근거 순서를 손실 없이 저장 레코드로 변환한다.

        Args:
            domain: 저장할 장애 aggregate.

        Returns:
            Self: 현재 개정과 소유 근거를 포함한 레코드.
        """
        return cls(
            id=domain.uid,
            version=domain.version,
            created_at=domain.created_at.astimezone(UTC).replace(tzinfo=None),
            updated_at=domain.updated_at.astimezone(UTC).replace(tzinfo=None),
            project_id=domain.project_id,
            symptom=domain.symptom,
            references=list(domain.references),
            status=domain.status.value,
            transfers=list(domain.transfers),
            replacement_id=domain.replacement_id,
            resolution=domain.resolution,
            revision=domain.revision,
            evidence=[
                IncidentEvidenceModel.from_domain(item, domain.uid, number)
                for number, item in enumerate(domain.evidence, 1)
            ],
        )

    @override
    def to_domain(self) -> Incident:
        """저장된 순서와 UTC 시각으로 요청에 독립적인 장애를 복원한다.

        Returns:
            Incident: 실제 해결 여부와 원래 근거가 유지된 장애.
        """
        return Incident(
            uid=self.id,
            version=self.version,
            created_at=self.created_at.replace(tzinfo=UTC),
            updated_at=self.updated_at.replace(tzinfo=UTC),
            project_id=self.project_id,
            symptom=self.symptom,
            references=self.references,
            status=IncidentStatus(self.status),
            transfers=self.transfers,
            replacement_id=self.replacement_id,
            resolution=self.resolution,
            revision=self.revision,
            evidence=tuple(item.to_domain() for item in self.evidence),
        )


@Table()
class IncidentEvidenceModel(AbstractTable):
    """장애가 소유하는 확인 근거를 순번과 함께 저장한다.

    Attributes:
        incident_id: 조회하거나 변경할 원 장애 식별자.
        number: 장애 안에서 보존하는 근거의 순번.
        kind: 관찰·재현·수정·회귀의 구분.
        detail: 실제로 관찰한 실패 또는 수행 결과.
        references: 원문과 실행 결과로 돌아갈 출처 목록.
        passed: 회귀 시험의 실제 결과이며 다른 근거는 None.
    """

    __tablename__ = "core_incident_evidence"
    incident_id: Mapped[UUID] = mapped_column(
        Uuid(), ForeignKey("core_incidents.id"), primary_key=True
    )
    number: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    detail: Mapped[str] = mapped_column(String, nullable=False)
    references: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    passed: Mapped[bool | None] = mapped_column(Boolean)

    @classmethod
    def from_domain(cls, domain: IncidentEvidence, incident_id: UUID, number: int) -> Self:
        """값 객체를 소유 장애와 순번에 연결한다.

        Args:
            domain: 실제 확인 근거.
            incident_id: 소유 장애의 ID.
            number: 저장 순번.

        Returns:
            Self: 원문과 참조를 보존한 자식 레코드.
        """
        return cls(
            incident_id=incident_id,
            number=number,
            kind=domain.kind.value,
            detail=domain.detail,
            references=list(domain.references),
            passed=domain.passed,
        )

    def to_domain(self) -> IncidentEvidence:
        """기록 당시의 확인 종류와 실제 시험 결과를 복원한다.

        Returns:
            IncidentEvidence: 변경할 수 없는 과거 근거.
        """
        return IncidentEvidence(
            kind=IncidentEvidenceKind(self.kind),
            detail=self.detail,
            references=self.references,
            passed=self.passed,
        )

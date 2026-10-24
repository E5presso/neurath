"""장애의 원래 증상과 해결 근거를 보존하고 이관·대체를 성공과 구분한다."""

from collections.abc import Sequence
from typing import Self, override
from uuid import UUID, uuid7

from spakky.core.common.mutability import mutable
from spakky.domain.models.aggregate_root import AbstractAggregateRoot

from neurath.domain.enums.incident_evidence_kind import IncidentEvidenceKind
from neurath.domain.enums.incident_status import IncidentStatus
from neurath.domain.errors import RevisionConflict
from neurath.domain.values.incident_evidence import IncidentEvidence


@mutable
class Incident(AbstractAggregateRoot[UUID]):
    """한 장애의 확인 과정이며 원래 작업의 완료 상태를 변경하지 않는다.

    Attributes:
        project_id: 관련 프로젝트이며 전역 저장 장애는 None.
        symptom: 처음 관찰한 증상 원문.
        references: 처음 증상의 출처.
        evidence: 순서를 보존한 재관찰·재현·수정·회귀 이력.
        status: 미해결·이관·대체·해결 상태.
        transfers: 이관 대상과 사유의 누적 기록.
        replacement_id: 대체 사건의 실제 ID.
        resolution: 해결 시 기록한 설명.
        revision: 저장소가 비교하는 낙관적 개정.
    """

    project_id: UUID | None
    symptom: str
    references: Sequence[str]
    evidence: Sequence[IncidentEvidence] = ()
    status: IncidentStatus = IncidentStatus.OPEN
    transfers: Sequence[str] = ()
    replacement_id: UUID | None = None
    resolution: str = ""
    revision: int = 1

    @classmethod
    @override
    def next_id(cls) -> UUID:
        """원래 태스크와 구분되는 장애 식별자를 생성한다.

        Returns:
            UUID: 새 장애의 UUID7.
        """
        return uuid7()

    @classmethod
    def create(cls, project_id: UUID | None, symptom: str, references: Sequence[str]) -> Self:
        """출처를 가진 첫 증상으로 미해결 장애를 연다.

        Args:
            project_id: 관련 프로젝트 또는 전역 장애의 None.
            symptom: 원래 관찰 본문.
            references: 원문·오류·실행 결과 참조.

        Returns:
            Self: 아직 해결이나 이관되지 않은 사건.
        """
        return cls(uid=cls.next_id(), project_id=project_id, symptom=symptom, references=references)

    @override
    def validate(self) -> None:
        """최초 증상의 내용과 출처를 같은 근거 계약으로 검증한다."""
        IncidentEvidence(
            kind=IncidentEvidenceKind.OBSERVATION, detail=self.symptom, references=self.references
        )

    def require_revision(self, revision: int) -> None:
        """오래된 조회를 근거로 다른 기록을 덮어쓰지 못하게 한다.

        Args:
            revision: 호출자가 실제 조회한 개정.

        Raises:
            RevisionConflict: 현재 개정과 일치하지 않는 경우.
        """
        if self.revision != revision:
            raise RevisionConflict("Incident revision changed")

    def _require_open(self) -> None:
        """종료된 사건의 기존 근거를 뒤늦게 바꾸지 못하게 한다.

        Raises:
            ValueError: 해결 또는 대체된 사건인 경우.
        """
        if self.status in (IncidentStatus.RESOLVED, IncidentStatus.SUPERSEDED):
            raise ValueError("Incident is already resolved or superseded; open a linked incident")

    def record(self, evidence: IncidentEvidence) -> None:
        """기존 증상을 덮어쓰지 않고 실제 확인 내용을 뒤에 추가한다.

        Args:
            evidence: 출처와 회귀 결과가 검증된 근거.
        """
        self._require_open()
        self.evidence = (*self.evidence, evidence)

    def escalate(self, destination: str) -> None:
        """미해결 상태를 유지하면서 다음 담당자·티켓 참조를 남긴다.

        Args:
            destination: 이관 대상과 사유.

        Raises:
            ValueError: 이관 대상을 제공하지 않은 경우.
        """
        self._require_open()
        if not destination.strip():
            raise ValueError("Escalation requires a destination and reason")
        self.transfers = (*self.transfers, destination)
        self.status = IncidentStatus.ESCALATED

    def supersede(self, replacement: Incident) -> None:
        """다음 미해결 사건에 연결하며 원래 증상·근거·이관 이력을 남긴다.

        Args:
            replacement: 같은 범위에 존재하는 대체 사건.

        Raises:
            ValueError: 자기 자신·다른 범위·이미 종료된 사건을 지정한 경우.
        """
        self._require_open()
        replacement._require_open()
        if replacement.uid == self.uid or replacement.project_id != self.project_id:
            raise ValueError("Replacement must be another incident in the same scope")
        self.replacement_id = replacement.uid
        self.status = IncidentStatus.SUPERSEDED

    def resolve(self, explanation: str) -> None:
        """재현 뒤 수정·회귀 성공을 확인한 경우에만 장애를 해결한다.

        Args:
            explanation: 어떤 증상이 어떻게 해결됐는지 설명.

        Raises:
            ValueError: 설명 또는 순서가 맞는 최신 성공 근거가 없는 경우.
        """
        self._require_open()
        progress = 0
        for evidence in self.evidence:
            if evidence.kind is IncidentEvidenceKind.OBSERVATION:
                continue
            if evidence.kind is IncidentEvidenceKind.REPRODUCTION:
                progress = 1
                continue
            if evidence.kind is IncidentEvidenceKind.FIX:
                progress = 2 if progress >= 1 else 0
                continue
            if progress >= 2:
                progress = 3 if evidence.passed else 2
        if not explanation.strip() or progress != 3:
            raise ValueError(
                "Resolution requires reproduction, a later fix and latest passing regression"
            )
        self.resolution = explanation
        self.status = IncidentStatus.RESOLVED

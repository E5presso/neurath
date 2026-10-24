"""장애에 종속된 원문과 실제 확인 결과를 값 객체로 보존한다."""

from collections.abc import Sequence
from typing import override

from spakky.core.common.mutability import immutable
from spakky.domain.models.value_object import AbstractValueObject

from neurath.domain.enums.incident_evidence_kind import IncidentEvidenceKind


@immutable
class IncidentEvidence(AbstractValueObject):
    """출처 있는 관찰이며 기록 자체를 시험 성공으로 취급하지 않는다.

    Attributes:
        kind: 재관찰·재현·수정·회귀 시험 구분.
        detail: 실제 증상 또는 수행 내용.
        references: 재현 절차·실행 결과로 돌아갈 출처.
        passed: 회귀 시험의 실제 성공 여부. 다른 종류에서는 None.
    """

    kind: IncidentEvidenceKind
    detail: str
    references: Sequence[str]
    passed: bool | None = None

    @override
    def validate(self) -> None:
        """비어 있는 근거와 시험 결과를 꾸민 조합을 거절한다.

        Raises:
            ValueError: 내용·출처가 없거나 회귀 결과의 표현이 맞지 않는 경우.
        """
        if (
            not self.detail.strip()
            or not self.references
            or any(not x.strip() for x in self.references)
        ):
            raise ValueError("Incident evidence requires detail and source references")
        if (self.kind is IncidentEvidenceKind.REGRESSION) != (self.passed is not None):
            raise ValueError("Only regression evidence requires a pass/fail outcome")

"""수행자 또는 검토자가 실제 관찰 근거와 함께 제출한 보고다."""

from collections.abc import Sequence
from typing import override

from spakky.core.common.mutability import immutable
from spakky.domain.models.value_object import AbstractValueObject


@immutable
class DelegationReport(AbstractValueObject):
    """수행자 또는 검토자가 실제 관찰 근거와 함께 제출한 보고다.

    Attributes:
        summary: 수행 또는 검토 결과의 원문.
        references: 산출물·검사·검토 후보의 참조.
        remaining_work: 아직 해결하지 못한 범위이며 없으면 None.
    """

    summary: str
    references: Sequence[str]
    remaining_work: str | None = None

    @override
    def validate(self) -> None:
        """근거 없는 결과 보고와 공백 남은 일을 거부한다.

        Raises:
            ValueError: 본문·근거·남은 일 표현이 잘못된 경우.
        """
        if (
            not self.summary.strip()
            or not self.references
            or any(not r.strip() for r in self.references)
        ):
            raise ValueError("Delegation report requires summary and evidence")
        if self.remaining_work is not None and not self.remaining_work.strip():
            raise ValueError("Remaining work must be non-empty when present")

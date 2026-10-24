"""요청된 회고의 교훈에 실제 검증·적용·보류·철회 관찰을 보존한다."""

from collections.abc import Sequence
from enum import StrEnum
from typing import override

from spakky.core.common.mutability import immutable
from spakky.domain.models.value_object import AbstractValueObject


class LessonState(StrEnum):
    """교훈의 현재 적용 상태를 효과 관찰과 구분한다.

    Attributes:
        PROPOSED: 회고에서 제안했으나 검증 전인 후보.
        VALIDATED: 실패 재현과 정상 대조를 확인한 후보.
        APPLIED: 명시된 관련 범위에 실제 적용한 상태.
        DEFERRED: 이유를 보존하고 적용하지 않은 상태.
        WITHDRAWN: 악화 또는 잘못된 교훈으로 철회한 상태.
    """

    PROPOSED = "proposed"
    VALIDATED = "validated"
    APPLIED = "applied"
    DEFERRED = "deferred"
    WITHDRAWN = "withdrawn"


@immutable
class LessonObservation(AbstractValueObject):
    """동일 교훈의 검증과 후속 효과를 순서대로 남기는 관찰이다.

    Attributes:
        state: 이 관찰 이후의 적용 상태.
        reason: 개선·보류·철회의 이유와 실제 효과.
        references: 실패 사례·정상 대조·실제 적용의 관찰 참조.
        failure_case: 원 실패 사례가 개선됐는지 확인한 근거.
        normal_case: 정상 동작이 유지됐는지 확인한 근거.
        effective: 실제 관련 수행 효과이며 확인 전은 None.
    """

    state: LessonState
    reason: str
    references: Sequence[str]
    failure_case: str = ""
    normal_case: str = ""
    effective: bool | None = None

    @override
    def validate(self) -> None:
        """말뿐인 검증·적용과 근거 없는 보류·철회를 거절한다.

        Raises:
            ValueError: 이유·근거 또는 검증 대조가 빠진 경우.
        """
        if (
            not self.reason.strip()
            or not self.references
            or any(not item.strip() for item in self.references)
        ):
            raise ValueError("Lesson observations require reasons and evidence")
        if self.state is LessonState.VALIDATED and (
            not self.failure_case.strip() or not self.normal_case.strip()
        ):
            raise ValueError("Validate both the original failure and normal control")

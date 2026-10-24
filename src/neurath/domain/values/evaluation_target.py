"""독립 평가가 대조할 관련 작업과 실제 후보·검증 자료를 고정한다."""

from collections.abc import Sequence
from enum import StrEnum
from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.domain.models.value_object import AbstractValueObject


class EvaluationKind(StrEnum):
    """작업 결과 평가와 요청된 회고 평가를 구분한다.

    Attributes:
        RESULT: 사용자 요구와 실제 결과를 대조하는 평가.
        REFLECTION: 사용자가 요청한 문제 원인과 개선 후보의 평가.
    """

    RESULT = "result"
    REFLECTION = "reflection"


@immutable
class EvaluationTarget(AbstractValueObject):
    """후보 개정은 단계의 target_revision에, 관련 범위와 자료는 이 값에 보존한다.

    Attributes:
        kind: 결과 또는 회고 평가의 목적.
        task_ids: 영향을 대조할 기존 작업 ID이며 빈 목록은 연결 태스크만 뜻한다.
        artifacts: 평가자가 실제로 열어 대조할 산출물 참조.
        verification: 실행·검사·문제 관찰의 근거 참조.
    """

    kind: EvaluationKind
    task_ids: Sequence[UUID] = ()
    artifacts: Sequence[str]
    verification: Sequence[str]

    @override
    def validate(self) -> None:
        """산출물·검증 자료가 없거나 작업 범위가 중복된 후보를 거절한다.

        Raises:
            ValueError: 필수 참조가 비었거나 작업이 중복된 경우.
        """
        if len(set(self.task_ids)) != len(self.task_ids):
            raise ValueError("Evaluation task scope must be unique")
        if (
            not self.artifacts
            or not self.verification
            or any(not value.strip() for value in (*self.artifacts, *self.verification))
        ):
            raise ValueError("Evaluation requires actual artifacts and verification references")

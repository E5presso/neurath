"""실제 외부 의존과 재개 범위 및 해소 관찰을 보존한다."""

from typing import override

from spakky.core.common.mutability import immutable
from spakky.domain.models.value_object import AbstractValueObject


@immutable
class ExternalWait(AbstractValueObject):
    """실제 외부 의존과 재개 범위 및 해소 관찰을 보존한다.

    Attributes:
        target: 기다리는 외부 작업·담당자·필요 조작.
        condition: 대기를 해소할 구체적인 조건.
        resume_scope: 해소 후 기존 지시 안에서 이어갈 범위.
        observation: 외부 의존이 남아 있다는 관찰.
        resolution: 재개할 때 관찰한 해소 근거.
    """

    target: str
    condition: str
    resume_scope: str
    observation: str
    resolution: str | None = None

    @override
    def validate(self) -> None:
        """대상·조건·후속 범위·관찰과 선택적인 해소 관찰이 공백인지 검사한다.

        각 필드의 기입 여부만 확인하며 외부 의존의 실재 여부는 검사하지 않는다.

        Raises:
            ValueError: 대상·조건·후속 범위·관찰 중 하나가 공백이거나 지정한 resolution이 공백인 경우.
        """
        for value in (self.target, self.condition, self.resume_scope, self.observation):
            if not value.strip():
                raise ValueError("external_wait must be non-empty")
        if self.resolution is not None and not self.resolution.strip():
            raise ValueError("resolution must be non-empty")

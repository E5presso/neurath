"""정정 전 정의를 덮어쓰지 않는 요구 개정이다."""

from collections.abc import Sequence
from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.domain.models.value_object import AbstractValueObject


@immutable
class TaskDefinition(AbstractValueObject):
    """정정 전 정의를 덮어쓰지 않는 요구 개정이다.

    Attributes:
        number: 태스크 안에서 증가하는 정의 번호.
        source_id: 원문 또는 실제 정정의 출처.
        title: 수행할 일의 제목.
        required_result: 달성해야 할 결과.
        dependencies: 먼저 성공해야 하는 같은 프로젝트의 태스크들.
    """

    number: int
    source_id: UUID
    title: str
    required_result: str
    dependencies: Sequence[UUID] = ()

    @override
    def validate(self) -> None:
        """양수 개정 번호·비어 있지 않은 목표·중복 없는 의존 ID를 확인한다.

        의존 대상의 존재와 순환은 전체 태스크 그래프가 필요한 Task에서 검사한다.

        Raises:
            ValueError: 번호·제목·결과 또는 의존 목록이 유효하지 않은 경우.
        """
        if not self.title.strip():
            raise ValueError("title must be non-empty")
        if not self.required_result.strip():
            raise ValueError("required_result must be non-empty")
        if self.number < 1 or len(set(self.dependencies)) != len(self.dependencies):
            raise ValueError("Invalid definition number or duplicate dependency")

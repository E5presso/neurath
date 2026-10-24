"""저장한 내용의 확실성과 역할을 구분한다."""

from collections.abc import Sequence
from enum import StrEnum
from typing import override

from spakky.core.common.mutability import immutable
from spakky.domain.models.value_object import AbstractValueObject


class EnclaveKind(StrEnum):
    """저장한 내용의 확실성과 역할을 구분한다.

    Attributes:
        FACT: 출처로 확인한 현재 사실.
        ASSUMPTION: 아직 확인하지 않은 가정.
        DECISION: 작업 중 선택한 판단.
    """

    FACT = "fact"
    ASSUMPTION = "assumption"
    DECISION = "decision"


@immutable
class EnclaveFact(AbstractValueObject):
    """짧은 현재 맥락과 상세 자료로 돌아갈 근거를 보존한다.

    Attributes:
        key: 같은 범위에서 정정·삭제할 항목의 이름.
        value: 다음 실행에 필요한 현재 내용.
        kind: 사실·가정·판단의 구분.
        references: 원문이나 상세 자료를 선택 조회할 참조.
    """

    key: str
    value: str
    kind: EnclaveKind
    references: Sequence[str]

    @override
    def validate(self) -> None:
        """내용이나 근거가 없는 항목을 거절한다.

        Raises:
            ValueError: 키·내용·근거가 비어 있거나 참조가 공백인 경우.
        """
        if not self.key.strip() or not self.value.strip():
            raise ValueError("Enclave key and value are required")
        if not self.references or any(not reference.strip() for reference in self.references):
            raise ValueError("Enclave source references are required")


@immutable
class EnclaveChange(AbstractValueObject):
    """현재 내용과 구분되는 특정 개정의 저장·삭제 이력이다.

    Attributes:
        number: enclave 안에서 증가하는 변경 순번.
        key: 변경한 항목의 이름.
        fact: 저장한 내용이며 명시적 삭제 이력에서는 None.
    """

    number: int
    key: str
    fact: EnclaveFact | None

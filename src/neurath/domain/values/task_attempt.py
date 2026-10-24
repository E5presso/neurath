"""실제 관찰 결과의 성공·실패·부분 수행을 구분한다."""

from collections.abc import Sequence
from enum import StrEnum
from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.domain.models.value_object import AbstractValueObject

from neurath.domain.errors import InvalidTaskState


class Outcome(StrEnum):
    """실제 관찰 결과의 성공·실패·부분 수행을 구분한다.

    Attributes:
        SUCCEEDED: 현재 요구를 충족한 관찰.
        FAILED: 실패와 남은 일.
        PARTIAL: 일부 수행과 남은 일.
    """

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PARTIAL = "partial"


@immutable
class SubmittedResult(AbstractValueObject):
    """제출 자료이며 실제 결과 확정이나 성공을 뜻하지 않는다.

    Attributes:
        summary: 수행자가 제출한 후보 설명.
        references: 후보 산출물과 보고의 참조.
    """

    summary: str
    references: Sequence[str] = ()

    @override
    def validate(self) -> None:
        """빈 후보 설명과 참조를 거부한다.

        Raises:
            ValueError: 후보 설명이나 참조가 공백만 포함한 경우.
        """
        if not self.summary.strip():
            raise ValueError("summary must be non-empty")
        for reference in self.references:
            if not reference.strip():
                raise ValueError("reference must be non-empty")


@immutable
class TaskResult(AbstractValueObject):
    """호출자가 관찰한 결과와 여전히 남은 일을 보존한다.

    Attributes:
        outcome: 성공·실패·부분 수행의 구분.
        summary: 실제 결과 설명.
        observations: 명령·산출물·검토 등 결과와 연결된 관찰 참조.
        remaining_work: 실패·부분 수행 후 여전히 남은 요구.
        exit_code: 명령 결과인 경우 관찰한 종료 코드.
    """

    outcome: Outcome
    summary: str
    observations: Sequence[str]
    remaining_work: str | None = None
    exit_code: int | None = None

    @override
    def validate(self) -> None:
        """관찰 참조와 결과 설명을 요구하고 성공·실패·남은 일의 일관성을 검사한다.

        성공에는 남은 일이 없어야 하며 종료 코드는 None 또는 0이어야 한다.
        실패·부분 수행에는 남은 일이 필요하다. 참조 문자열의 존재를 검사할 뿐
        외부 산출물이나 명령의 진위를 확인하지 않는다.

        Raises:
            ValueError: 결과 설명·관찰·남은 일이 비어 있는 경우.
            InvalidTaskState: 성공 주장과 남은 일 또는 종료 코드가 충돌하는 경우.
        """
        if not self.summary.strip():
            raise ValueError("summary must be non-empty")
        if not self.observations:
            raise ValueError("Observed result references are required")
        for observation in self.observations:
            if not observation.strip():
                raise ValueError("observation must be non-empty")
        if self.outcome is Outcome.SUCCEEDED and (
            self.remaining_work is not None or self.exit_code not in (None, 0)
        ):
            raise InvalidTaskState("Success contradicts remaining work or command failure")
        if self.outcome is Outcome.SUCCEEDED:
            return
        if self.remaining_work is None or not self.remaining_work.strip():
            raise ValueError("remaining_work must be non-empty")


@immutable
class TaskAttempt(AbstractValueObject):
    """태스크가 소유하는 특정 요구 개정의 실행 시도 기록이다.

    Attributes:
        number: 태스크 안에서 구분하는 시도 번호.
        definition_number: 시작할 때 고정한 요구 개정.
        session_id: 시도를 시작한 세션.
        submission: 확정 전 후보 자료.
        result: 실제 관찰을 보고한 결과.
    """

    number: int
    definition_number: int
    session_id: UUID
    submission: SubmittedResult | None = None
    result: TaskResult | None = None

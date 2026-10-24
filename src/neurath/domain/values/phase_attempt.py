"""단계 실행의 진행·대기·확정 결과를 구분한다."""

from collections.abc import Sequence
from enum import StrEnum
from typing import override

from spakky.core.common.mutability import immutable
from spakky.domain.models.value_object import AbstractValueObject


class PhaseStatus(StrEnum):
    """단계 실행의 진행·대기·확정 결과를 구분한다.

    Attributes:
        PENDING: 아직 현재 정의로 실행하거나 생략하지 않은 상태.
        RUNNING: 실행을 예약했으며 실제 결과는 아직 받지 않은 상태.
        WAITING: 응답 유실로 외부 결과를 확인해야 하는 상태.
        SUCCEEDED: 정의의 검증 조건을 충족한 상태.
        FAILED: 실패·시간 초과·중단으로 재시도 판단이 필요한 상태.
        SKIPPED: 정의에 허용된 조건에 따라 생략한 상태.
    """

    PENDING = "pending"
    RUNNING = "running"
    WAITING = "waiting"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


@immutable
class PhaseResult(AbstractValueObject):
    """실행자가 관찰한 결과와 검증 대상·근거를 보고한다.

    Attributes:
        status: 성공·실패·결과 불명 중 보고할 상태.
        target_revision: 실제로 실행·검사한 대상의 개정.
        summary: 성공·실패 또는 결과 불명의 이유.
        evidence: 명령·산출물·검토 결과의 참조 목록.
        checks: 실제로 충족한 검사 이름들.
        output: 한도 안에서 보존한 실행 출력.
        exit_code: 확인된 프로세스 종료 코드. 결과 불명이면 None.
    """

    status: PhaseStatus
    target_revision: str
    summary: str
    evidence: Sequence[str] = ()
    checks: Sequence[str] = ()
    output: str = ""
    exit_code: int | None = None

    @override
    def validate(self) -> None:
        """빈 설명과 성공에 모순되는 종료 코드를 거부한다.

        Raises:
            ValueError: 대상·설명 또는 결과 상태가 유효하지 않은 경우.
        """
        if not self.target_revision.strip() or not self.summary.strip():
            raise ValueError("Result target and summary are required")
        if self.status not in (PhaseStatus.SUCCEEDED, PhaseStatus.FAILED, PhaseStatus.WAITING):
            raise ValueError("Only execution outcomes can be reported")
        if self.status is PhaseStatus.SUCCEEDED and (
            not self.evidence or self.exit_code not in (None, 0)
        ):
            raise ValueError(
                "Successful results require evidence and cannot have a failing exit code"
            )


@immutable
class PhaseAttempt(AbstractValueObject):
    """한 단계의 예약·실행·결과를 같은 시도 번호로 연결한다.

    Attributes:
        number: run 안에서 증가하는 시도 번호.
        definition_number: 시도 시작 시 고정한 정의 개정 번호.
        phase_key: 실행할 단계 식별자.
        status: 시도의 현재 진행·결과 상태.
        result: 마지막 관찰 결과. 실행 예약 직후에는 None.
        skip_reason: 선택 단계 생략의 근거. 실행 시도에는 None.
    """

    number: int
    definition_number: int
    phase_key: str
    status: PhaseStatus
    result: PhaseResult | None = None
    skip_reason: str | None = None

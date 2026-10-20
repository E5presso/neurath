"""선택한 절차의 단계 정의와 개별 실행 결과를 불변 값으로 표현한다."""

from collections.abc import Sequence
from enum import StrEnum
from math import isfinite
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
class PhaseDefinition(AbstractValueObject):
    """한 단계에서 실행할 명령과 그 결과를 판단할 조건을 고정한다.

    Attributes:
        key: 정의 개정 사이에서 같은 단계를 식별하는 이름.
        purpose: 이 단계가 만들어야 하는 결과.
        arguments: 셸 해석 없이 실행할 프로그램과 인자.
        directory: 명령을 실행할 작업 디렉터리.
        target_revision: 검사 대상 소스·산출물의 개정 참조.
        checks: 결과 보고에서 충족해야 하는 검사 이름들.
        skip_condition: 생략을 허용하는 조건 설명. 필수 단계는 None.
        timeout: 프로세스를 기다릴 최대 초.
        output_limit: 결과에 보존할 출력의 최대 바이트 수.
        max_attempts: 같은 대상·태스크 요구에서 이 단계에 허용할 실제 실행 횟수.
    """

    key: str
    purpose: str
    arguments: Sequence[str]
    directory: str
    target_revision: str
    checks: Sequence[str] = ("exit:0",)
    skip_condition: str | None = None
    timeout: float = 60.0
    output_limit: int = 65536
    max_attempts: int = 3

    @override
    def validate(self) -> None:
        """식별·실행 대상·검증 조건과 실행 한도가 빠진 정의를 거부한다.

        Raises:
            ValueError: 필수 문자열·명령·검사 또는 양수 한도가 유효하지 않은 경우.
        """
        if not all(
            value.strip()
            for value in (self.key, self.purpose, self.directory, self.target_revision)
        ):
            raise ValueError("Phase identity, purpose, directory and target revision are required")
        if not self.arguments or not self.arguments[0].strip():
            raise ValueError("An executable is required")
        if (
            not self.checks
            or len(set(self.checks)) != len(self.checks)
            or any(not check.strip() for check in self.checks)
        ):
            raise ValueError("Checks must be nonempty and unique")
        if (
            not isfinite(self.timeout)
            or self.timeout <= 0
            or self.output_limit < 1
            or self.max_attempts < 1
        ):
            raise ValueError("Execution limits must be positive")
        if self.skip_condition is not None and not self.skip_condition.strip():
            raise ValueError("An optional phase requires its skip condition")


@immutable
class WorkflowDefinition(AbstractValueObject):
    """선택한 스킬의 특정 버전과 순서가 있는 단계들을 보존한다.

    Attributes:
        skill: 실행할 스킬 이름.
        version: 시작 또는 절차 정정 시 선택한 정의 버전.
        phases: 실행 순서대로 고정한 단계들.
        inputs: 해당 실행에서 고정한 (이름, 값) 쌍의 불변 목록.
    """

    skill: str
    version: str
    phases: Sequence[PhaseDefinition]
    inputs: Sequence[tuple[str, str]]

    @override
    def validate(self) -> None:
        """스킬·버전·단계가 없거나 단계 식별자가 중복된 정의를 거부한다.

        Raises:
            ValueError: 스킬·버전·단계 또는 단계 식별자의 유일성이 부족한 경우.
        """
        if not self.skill.strip() or not self.version.strip() or not self.phases:
            raise ValueError("Skill, version and phases are required")
        if len({phase.key for phase in self.phases}) != len(self.phases):
            raise ValueError("Phase keys must be unique")
        if len({key for key, value in self.inputs}) != len(self.inputs) or any(
            not key.strip() for key, value in self.inputs
        ):
            raise ValueError("Input names must be nonempty and unique")


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


@immutable
class WorkflowRevision(AbstractValueObject):
    """절차 정의를 적용한 태스크 요구 개정과 변경 이유를 보존한다.

    Attributes:
        definition: 이 개정에서 선택한 스킬·단계·입력.
        task_definition_number: 같은 시점의 태스크 요구 개정.
        reason: 최초 시작 또는 절차 수정의 이유.
    """

    definition: WorkflowDefinition
    task_definition_number: int
    reason: str

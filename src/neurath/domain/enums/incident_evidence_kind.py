"""장애 해결 과정에서 확인한 근거의 목적을 구분한다."""

from enum import StrEnum


class IncidentEvidenceKind(StrEnum):
    """증상·재현·수정·회귀 시험을 각각 보존하는 근거 종류다.

    Attributes:
        OBSERVATION: 처음 증상 또는 실제 재관찰 결과.
        REPRODUCTION: 증상을 다시 확인한 절차와 실행 근거.
        FIX: 재현된 증상을 수정한 내용과 출처.
        REGRESSION: 수정 이후 실행한 시험의 실제 성공·실패 결과.
    """

    OBSERVATION = "observation"
    REPRODUCTION = "reproduction"
    FIX = "fix"
    REGRESSION = "regression"

"""수행 보고와 검토 보고의 책임을 구분한다."""

from enum import StrEnum


class DelegationRole(StrEnum):
    """수행 보고와 검토 보고의 책임을 구분한다.

    Attributes:
        EXECUTOR: 맡은 범위의 수행자.
        REVIEWER: 기존 산출물의 독립 검토자.
    """

    EXECUTOR = "executor"
    REVIEWER = "reviewer"

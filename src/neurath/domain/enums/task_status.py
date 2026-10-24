"""원장의 현재 태스크 상태를 구분한다."""

from enum import StrEnum


class TaskStatus(StrEnum):
    """원장의 현재 태스크 상태를 구분한다.

    Attributes:
        PENDING: 수행할 결과가 남은 상태.
        ACTIVE: 현재 시도를 수행하는 상태.
        WAITING: 실제 외부 의존을 기다리는 상태.
        SUCCEEDED: 현재 요구의 성공 결과가 있는 상태.
        FAILED: 실패한 시도와 남은 요구를 보존한 상태.
        INVALIDATED: 실제 정정으로 무효화한 상태.
    """

    PENDING = "pending"
    ACTIVE = "active"
    WAITING = "waiting"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    INVALIDATED = "invalidated"

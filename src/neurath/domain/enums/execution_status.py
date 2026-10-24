"""세션 연결이 아닌 현재 실행의 관찰 상태다."""

from enum import StrEnum


class ExecutionStatus(StrEnum):
    """세션 연결이 아닌 현재 실행의 관찰 상태다.

    Attributes:
        RUNNING: 현재 턴의 동작을 허용하는 상태.
        PAUSED: 실패 또는 외부 대기로 제어권을 반환한 상태.
        CANCELLED: 실제 중단 사건이 확인된 턴.
        ENDED: 호스트 연결 종료가 관찰된 상태.
    """

    RUNNING = "running"
    PAUSED = "paused"
    CANCELLED = "cancelled"
    ENDED = "ended"

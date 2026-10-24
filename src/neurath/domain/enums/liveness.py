"""실행 어댑터가 확인한 특정 실행의 생존 상태다."""

from enum import StrEnum


class Liveness(StrEnum):
    """실행 어댑터가 확인한 특정 실행의 생존 상태다.

    Attributes:
        RUNNING: 해당 실행이 아직 진행 중임.
        STOPPED: 해당 실행의 실제 종료를 확인함.
        UNKNOWN: 일치하는 실행을 관찰할 수 없음.
    """

    RUNNING = "running"
    STOPPED = "stopped"
    UNKNOWN = "unknown"

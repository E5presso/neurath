"""호스트 사건과 다음 실행 판정을 완료 여부와 구분해 표현한다."""

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


class HookAction(StrEnum):
    """호스트가 유지·계속·중지해야 할 동작이며 태스크 성공을 뜻하지 않는다.

    Attributes:
        ALLOW: 네이티브 권한 판단을 유지하며 이 훅의 추가 제한이 없음.
        CONTINUE: 남은 일을 계속하도록 한 번 피드백함.
        PAUSE: 모델 재시도 없이 호스트에 제어권을 반환함.
    """

    ALLOW = "allow"
    CONTINUE = "continue"
    PAUSE = "pause"


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

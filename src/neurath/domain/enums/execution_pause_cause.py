"""대기·장애·취소 요청을 같은 실행 상태의 서로 다른 원인으로 구분한다."""

from enum import StrEnum


class ExecutionPauseCause(StrEnum):
    """해소 사건이 다른 중지 원인을 구분한다.

    Attributes:
        WAITING: 실제 외부 의존 해소를 기다림.
        FAILURE: 호스트 또는 하네스 오류.
        NO_PROGRESS: 동일 Stop 피드백 반복으로 제어권을 반환함.
        CANCELLATION: 실제 중단 요청의 종료 확인 대기.
    """

    WAITING = "waiting"
    FAILURE = "failure"
    NO_PROGRESS = "no_progress"
    CANCELLATION = "cancellation"

"""배정 준비부터 실제 결과·중단 관찰까지의 상태다."""

from enum import StrEnum


class DelegationStatus(StrEnum):
    """배정 준비부터 실제 결과·중단 관찰까지의 상태다.

    Attributes:
        PREPARED: 계획만 저장했고 아직 전달하지 않음.
        ASSIGNED: 수신 경로에 배정을 제출함.
        ACCEPTED: 수신자가 최신 배정을 수락함.
        RUNNING: 수신자가 실제 작업 시작을 보고함.
        COMPLETED: 수신자의 결과 보고를 받음. 태스크 성공과 별개.
        STOP_REQUESTED: 정정·취소를 반영했으나 실제 중단은 미확인.
        STOPPED: 해당 실행이 중단됐다는 관찰이 있음.
    """

    PREPARED = "prepared"
    ASSIGNED = "assigned"
    ACCEPTED = "accepted"
    RUNNING = "running"
    COMPLETED = "completed"
    STOP_REQUESTED = "stop_requested"
    STOPPED = "stopped"

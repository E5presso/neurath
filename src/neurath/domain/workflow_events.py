"""단계 실행 요청·관찰 결과·커밋된 대기 상태를 전달한다."""

from spakky.core.common.mutability import immutable
from spakky.domain.models.event import AbstractDomainEvent

from neurath.domain.workflow_records import PhaseAttempt, PhaseDefinition, PhaseResult


@immutable
class PhaseExecutionRequested(AbstractDomainEvent):
    """저장된 시도를 실행하거나 동일 시도의 결과를 관찰하도록 요청한다.

    Attributes:
        project_id: 실행을 소유한 프로젝트.
        session_id: 실행을 소유한 세션.
        run_id: 시도를 보존한 워크플로우.
        phase: 시도 당시의 실행 대상과 제한.
        attempt: DB에 기록한 시도.
        fresh: 이번 트랜잭션에서 처음 예약한 시도인지 여부.
    """

    project_id: str
    session_id: str
    run_id: str
    phase: PhaseDefinition
    attempt: PhaseAttempt
    fresh: bool


@immutable
class PhaseExecutionObserved(AbstractDomainEvent):
    """외부 실행기가 반환한 결과를 원래 워크플로우 시도에 연결한다.

    Attributes:
        project_id: 시도를 소유한 프로젝트.
        session_id: 시도를 소유한 세션.
        run_id: 결과를 기록할 워크플로우.
        attempt_number: 실제 관찰한 시도 번호.
        result: 실행·조회에서 확인한 성공·실패·결과 불명.
    """

    project_id: str
    session_id: str
    run_id: str
    attempt_number: int
    result: PhaseResult


@immutable
class PhaseWaitingRecorded(AbstractDomainEvent):
    """새로운 결과 불명 상태가 저장되어 사용자 안내를 요청한다.

    Attributes:
        request_id: 대기 중인 외부 시도를 식별하는 ID.
        reason: 저장된 결과 불명의 원인.
    """

    request_id: str
    reason: str

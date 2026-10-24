"""외부 실행기가 반환한 결과를 원래 워크플로우 시도에 연결한다."""

from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.domain.models.event import AbstractDomainEvent

from neurath.domain.values.phase_attempt import PhaseResult


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

    project_id: UUID
    session_id: UUID
    run_id: UUID
    attempt_number: int
    result: PhaseResult

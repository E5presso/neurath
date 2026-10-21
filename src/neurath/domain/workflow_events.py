"""커밋된 단계 실행 요청을 외부 실행 핸들러에 전달한다."""

from spakky.core.common.mutability import immutable
from spakky.domain.models.event import AbstractDomainEvent

from neurath.domain.workflow_records import PhaseAttempt, PhaseDefinition


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

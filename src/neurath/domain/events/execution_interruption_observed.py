"""정확한 턴의 중단 요청에 대한 실제 호스트 관찰을 전달한다."""

from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.domain.models.event import AbstractDomainEvent

from neurath.domain.enums.liveness import Liveness


@immutable
class ExecutionInterruptionObserved(AbstractDomainEvent):
    """정확한 턴의 중단 요청에 대한 실제 호스트 관찰을 전달한다.

    Attributes:
        execution_id: 중단을 요청한 실행.
        turn_id: 관찰 대상 턴.
        liveness: 실제 관찰 결과이며 UNKNOWN은 종료 확인이 아니다.
    """

    execution_id: UUID
    turn_id: str
    liveness: Liveness

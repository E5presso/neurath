"""추가 쓰기를 중지한 실제 실행의 종료 확인을 요청한다."""

from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.domain.models.event import AbstractDomainEvent


@immutable
class ExecutionCancellationRequested(AbstractDomainEvent):
    """추가 쓰기를 중지한 실제 실행의 종료 확인을 요청한다.

    Attributes:
        execution_id: 중단할 실행의 내부 식별자.
        turn_id: 중단 요청을 받은 정확한 호스트 턴.
    """

    execution_id: UUID
    turn_id: str

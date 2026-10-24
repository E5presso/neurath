"""현재 작성 임대의 실제 실행이 종료됐는지 조회하도록 요청한다."""

from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.domain.models.event import AbstractDomainEvent


@immutable
class WriterRecoveryRequested(AbstractDomainEvent):
    """현재 작성 임대의 실제 실행이 종료됐는지 조회하도록 요청한다.

    Attributes:
        writer_id: 회수할 작성 임대.
        execution_id: 관찰 당시 소유 실행.
        turn_id: 해당 실행의 정확한 턴.
        tool_use_id: 작성 도구 호출 식별자.
        generation: 관찰 뒤 다시 대조할 임대 세대.
    """

    writer_id: UUID
    execution_id: UUID
    turn_id: str
    tool_use_id: str
    generation: int

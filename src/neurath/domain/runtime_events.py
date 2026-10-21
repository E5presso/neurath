"""커밋된 중단·작성 회수 요청을 호스트 관찰에 전달한다."""

from spakky.core.common.mutability import immutable
from spakky.domain.models.event import AbstractDomainEvent


@immutable
class ExecutionCancellationRequested(AbstractDomainEvent):
    """추가 쓰기를 중지한 실제 실행의 종료 확인을 요청한다.

    Attributes:
        execution_id: 중단할 실행의 내부 식별자.
        turn_id: 중단 요청을 받은 정확한 호스트 턴.
    """

    execution_id: str
    turn_id: str


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

    writer_id: str
    execution_id: str
    turn_id: str
    tool_use_id: str
    generation: int

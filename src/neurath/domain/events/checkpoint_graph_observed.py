"""외부 작업의 성공 또는 실패를 원래 체크포인트에 연결한다."""

from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.domain.models.event import AbstractDomainEvent


@immutable
class CheckpointGraphObserved(AbstractDomainEvent):
    """외부 작업의 성공 또는 실패를 원래 체크포인트에 연결한다.

    Attributes:
        memory_id: 결과를 기록할 체크포인트 ID.
        directory: 실제 작업을 수행한 요청 경로.
        reference: 검증된 그래프 참조이며 실패면 None.
        error: 실패 관찰이며 성공이면 None.
    """

    memory_id: UUID
    directory: str
    reference: str | None
    error: str | None

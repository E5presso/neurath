"""검증과 저장이 끝난 보고에 연결된 그래프 갱신 요청이다."""

from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.domain.models.event import AbstractDomainEvent


@immutable
class CheckpointGraphRequested(AbstractDomainEvent):
    """검증과 저장이 끝난 보고에 연결된 그래프 갱신 요청이다.

    Attributes:
        memory_id: 커밋된 체크포인트 ID.
        directory: 명시적으로 요청한 Graphify 경로.
    """

    memory_id: UUID
    directory: str

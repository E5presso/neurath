"""커밋된 체크포인트의 외부 갱신 요청과 관찰 결과를 전달한다."""

from spakky.core.common.mutability import immutable
from spakky.domain.models.event import AbstractDomainEvent


@immutable
class CheckpointGraphRequested(AbstractDomainEvent):
    """검증과 저장이 끝난 보고에 연결된 그래프 갱신 요청이다.

    Attributes:
        memory_id: 커밋된 체크포인트 ID.
        directory: 명시적으로 요청한 Graphify 경로.
    """

    memory_id: str
    directory: str


@immutable
class CheckpointGraphObserved(AbstractDomainEvent):
    """외부 작업의 성공 또는 실패를 원래 체크포인트에 연결한다.

    Attributes:
        memory_id: 결과를 기록할 체크포인트 ID.
        directory: 실제 작업을 수행한 요청 경로.
        reference: 검증된 그래프 참조이며 실패면 None.
        error: 실패 관찰이며 성공이면 None.
    """

    memory_id: str
    directory: str
    reference: str | None
    error: str | None

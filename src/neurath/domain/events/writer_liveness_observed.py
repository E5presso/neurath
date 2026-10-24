"""작성 호출의 생존 관찰과 재검사할 임대 세대를 전달한다."""

from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.domain.models.event import AbstractDomainEvent

from neurath.domain.enums.liveness import Liveness


@immutable
class WriterLivenessObserved(AbstractDomainEvent):
    """작성 호출의 생존 관찰과 재검사할 임대 세대를 전달한다.

    Attributes:
        writer_id: 조회한 작성 임대.
        execution_id: 관찰 당시 소유 실행.
        generation: 관찰 뒤 대조할 임대 세대.
        liveness: 실제 작성 호출의 관찰 결과.
    """

    writer_id: UUID
    execution_id: UUID
    generation: int
    liveness: Liveness

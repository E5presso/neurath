"""커밋된 태스크의 최신 요구를 배정 처리자가 다시 읽게 한다."""

from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.domain.models.event import AbstractDomainEvent


@immutable
class TaskDefinitionChanged(AbstractDomainEvent):
    """커밋된 태스크의 최신 요구를 배정 처리자가 다시 읽게 한다.

    Attributes:
        task_id: 실제로 정정·무효화된 원 태스크.
    """

    task_id: UUID

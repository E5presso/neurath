"""원래 작업의 외부 의존이 실제로 해소됐음을 알린다."""

from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.domain.models.event import AbstractDomainEvent


@immutable
class TaskResumed(AbstractDomainEvent):
    """원 작업의 대기가 해소된 뒤 관련 실행 상태만 조정할 사건이다.

    Attributes:
        task_id: 같은 시도로 돌아온 원 작업.
    """

    task_id: UUID

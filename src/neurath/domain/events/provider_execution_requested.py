"""고정한 계획의 외부 실행을 커밋 후 요청한다."""

from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.domain.models.event import AbstractDomainEvent

from neurath.domain.values.provider_plan import ProviderPlan


@immutable
class ProviderExecutionRequested(AbstractDomainEvent):
    """고정한 계획의 외부 실행을 커밋 후 요청한다.

    Attributes:
        delegation_id: 검증하고 저장한 배정 ID.
        plan: 실제 모델·정책·작업 폴더.
        prompt: 원 지시·요구·범위가 담긴 입력.
    """

    delegation_id: UUID
    plan: ProviderPlan
    prompt: str

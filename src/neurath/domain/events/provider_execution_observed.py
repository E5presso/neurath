"""원 실행에 대한 실제 상태·출력 관찰이다."""

from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.domain.models.event import AbstractDomainEvent

from neurath.domain.enums.provider_status import ProviderStatus


@immutable
class ProviderExecutionObserved(AbstractDomainEvent):
    """원 실행에 대한 실제 상태·출력 관찰이다.

    Attributes:
        delegation_id: 관찰한 원 배정 ID.
        reference: 원 실행 자료 위치.
        status: 실제 관찰 상태.
        native_session_id: 실제 호스트 세션 ID.
        output: 실행 결과 본문.
        error: 실패 또는 불확실성의 설명.
    """

    delegation_id: UUID
    reference: str
    status: ProviderStatus
    native_session_id: str | None
    output: str
    error: str | None

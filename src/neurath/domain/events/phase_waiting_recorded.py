"""새로운 결과 불명 상태가 저장되어 사용자 안내를 요청한다."""

from spakky.core.common.mutability import immutable
from spakky.domain.models.event import AbstractDomainEvent


@immutable
class PhaseWaitingRecorded(AbstractDomainEvent):
    """새로운 결과 불명 상태가 저장되어 사용자 안내를 요청한다.

    Attributes:
        request_id: 대기 중인 외부 시도를 식별하는 ID.
        reason: 저장된 결과 불명의 원인.
    """

    request_id: str
    reason: str

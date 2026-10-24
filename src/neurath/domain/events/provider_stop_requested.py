"""원 요구 변경에 영향받은 provider 실행만 중단하도록 요청한다."""

from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.domain.models.event import AbstractDomainEvent


@immutable
class ProviderStopRequested(AbstractDomainEvent):
    """원 요구 변경에 영향받은 provider 실행만 중단하도록 요청한다.

    Attributes:
        delegation_id: 중단 요청이 커밋된 배정.
        sender_id: 원 배정의 책임 피어.
    """

    delegation_id: UUID
    sender_id: UUID

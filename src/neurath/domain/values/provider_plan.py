"""실행 전에 확정한 실제 provider 모델과 정책이다."""

from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.domain.models.value_object import AbstractValueObject

from neurath.domain.enums.provider_kind import ProviderKind
from neurath.domain.errors import InvalidTaskState


@immutable
class ProviderPlan(AbstractValueObject):
    """실행 전에 확정한 실제 provider 모델과 정책이다.

    Attributes:
        provider: 지원 공급자 이름.
        model: 공급자 조회에서 확인한 모델 ID.
        policy: 지원되는 명시적 실행 권한 정책.
        directory: 실행할 작업 디렉터리.
        parent_session_id: 배정한 Neurath 세션. 네이티브 부모 관계를 뜻하지 않는다.
    """

    provider: ProviderKind
    model: str
    policy: str
    directory: str
    parent_session_id: UUID

    @override
    def validate(self) -> None:
        """빈 계획과 암묵적 권한 상속을 거부한다.

        Raises:
            ValueError: 계획 필드가 비어 있거나 상속을 명시한 경우.
        """
        if (
            not all(
                value.strip()
                for value in (
                    self.provider,
                    self.model,
                    self.policy,
                    self.directory,
                )
            )
            or self.policy == "inherit"
        ):
            raise ValueError("Provider plan requires an explicit model and supported policy")

    def require_parent(self, session_id: UUID) -> None:
        """저장한 실행 계획이 실제 배정 세션의 계획인지 확인한다.

        Args:
            session_id: 현재 배정하는 세션.

        Raises:
            InvalidTaskState: 계획의 부모 세션이 다른 경우.
        """
        if self.parent_session_id != session_id:
            raise InvalidTaskState("Provider plan belongs to a different parent session")

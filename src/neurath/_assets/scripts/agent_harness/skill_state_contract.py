"""Session aggregate와 typed skill-state store가 공유하는 dependency-neutral 계약입니다."""

from abc import ABC, abstractmethod
from collections.abc import Mapping


class SessionKernelError(RuntimeError):
    """SessionKernel과 그 위 typed state adapter가 공유하는 base error입니다."""


class SkillStateStoreError(SessionKernelError):
    """SkillStateStore contract 위반의 base error입니다."""


class SkillStateReservedMutation(ABC):
    """Typed domain store가 소유하는 reserved namespace mutation contract입니다."""

    @property
    @abstractmethod
    def reserved_namespaces(self) -> frozenset[str]:
        """Mutation이 typed invariant로 소유하는 exact namespace를 반환합니다.

        Returns:
            이번 typed mutation이 invariant 검증 후 변경할 권한을 주장하는 namespace
            집합입니다.

        Raises:
            NotImplementedError: Concrete typed mutation이 ownership을 구현하지 않으면
                발생합니다.
        """
        raise NotImplementedError

    @abstractmethod
    def __call__(self, current: Mapping[str, object]) -> Mapping[str, object]:
        """Current skill state에 typed domain transition을 적용합니다.

        Args:
            current: Sibling namespace를 포함하는 current skill-state object입니다.

        Returns:
            Typed invariant를 통과하고 sibling namespace를 보존한 replacement object입니다.

        Raises:
            NotImplementedError: Concrete typed mutation이 transition을 구현하지 않으면
                발생합니다.
        """
        raise NotImplementedError

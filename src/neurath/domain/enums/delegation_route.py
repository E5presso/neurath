"""실제 피어·네이티브 자식·독립 실행의 관계를 구분한다."""

from enum import StrEnum


class DelegationRoute(StrEnum):
    """실제 피어·네이티브 자식·독립 실행의 관계를 구분한다.

    Attributes:
        PEER: 기존 피어에게 전달.
        CHILD: 실제 부모 관계가 있는 네이티브 자식에게 전달.
        PROVIDER: 별도 provider 실행.
    """

    PEER = "peer"
    CHILD = "child"
    PROVIDER = "provider"

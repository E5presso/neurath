"""기존 스킬의 선택적 회고 분기를 표현한다."""

from enum import StrEnum


class ReflectionChoice(StrEnum):
    """제안은 실행 요청과 구분하고 거절·무응답은 완료를 막지 않는다.

    Attributes:
        UNASKED: 문제가 없거나 아직 제안하지 않은 상태.
        OFFERED: 문제에 대해 한 번 제안한 상태.
        REQUESTED: 사용자가 직접 요청하거나 일반 문장으로 수락한 상태.
        DECLINED: 제안을 거절한 상태.
        UNANSWERED: 응답 없이 원 작업을 마무리하는 상태.
    """

    UNASKED = "unasked"
    OFFERED = "offered"
    REQUESTED = "requested"
    DECLINED = "declined"
    UNANSWERED = "unanswered"

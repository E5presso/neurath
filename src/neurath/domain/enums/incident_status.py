"""장애의 미해결 이관·대체와 실제 해결을 구분한다."""

from enum import StrEnum


class IncidentStatus(StrEnum):
    """기록 이동만으로 해결 성공이 되지 않는 장애 상태다.

    Attributes:
        OPEN: 해결 근거를 모으는 미해결 상태.
        ESCALATED: 다른 담당자에게 이관했지만 아직 미해결인 상태.
        SUPERSEDED: 대체 사건에 연결했으며 해결 성공은 아닌 상태.
        RESOLVED: 재현 뒤 수정·회귀 성공 근거로 해결한 상태.
    """

    OPEN = "open"
    ESCALATED = "escalated"
    SUPERSEDED = "superseded"
    RESOLVED = "resolved"

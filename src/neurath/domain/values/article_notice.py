"""제목 알림의 대기·응답 제출·폐기를 실제 열람과 구분한다."""

from enum import StrEnum
from uuid import UUID

from spakky.core.common.mutability import immutable


class ArticleNoticeStatus(StrEnum):
    """제목 알림의 대기·응답 제출·폐기를 실제 열람과 구분한다.

    Attributes:
        PENDING: 발행 당시 수신자로 확정했고 아직 훅에 제출하지 않음.
        SUBMITTED: 훅 응답에 제목을 제출했으며 실제 호스트 수신은 미확인.
        DISCARDED: 비활성·구독 해제·후속 개정으로 제목을 제출하지 않고 폐기함.
    """

    PENDING = "pending"
    SUBMITTED = "submitted"
    DISCARDED = "discarded"


@immutable
class ArticleNotice:
    """발행 당시 확정한 활성 구독자의 제목 알림이다.

    Attributes:
        peer_id: 발행 당시 활성 구독자.
        revision_number: 알릴 기사 개정.
        status: 대기·응답 제출·폐기의 구분이며 실제 열람을 뜻하지 않음.
    """

    peer_id: UUID
    revision_number: int
    status: ArticleNoticeStatus = ArticleNoticeStatus.PENDING

"""전체 본문을 반환한 한 개정의 열람이다."""

from uuid import UUID

from spakky.core.common.mutability import immutable


@immutable
class ArticleRead:
    """전체 본문을 반환한 한 개정의 열람이다.

    Attributes:
        peer_id: 본문을 선택 조회한 피어.
        revision_number: 실제 반환한 개정.
    """

    peer_id: UUID
    revision_number: int

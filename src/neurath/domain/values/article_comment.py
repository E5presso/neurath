"""작성자가 실제 읽은 개정에 붙인 댓글이다."""

from uuid import UUID

from spakky.core.common.mutability import immutable


@immutable
class ArticleComment:
    """작성자가 실제 읽은 개정에 붙인 댓글이다.

    Attributes:
        number: 기사 안에서 증가하는 댓글 순서.
        revision_number: 읽고 논의한 기사 개정.
        peer_id: 댓글 작성 피어.
        body: 댓글 원문.
    """

    number: int
    revision_number: int
    peer_id: UUID
    body: str

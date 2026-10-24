"""작성자가 실제 읽은 개정에 붙인 댓글이다."""

from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.domain.models.value_object import AbstractValueObject


@immutable
class ArticleComment(AbstractValueObject):
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

    @override
    def validate(self) -> None:
        """기존 댓글 본문 규칙을 생성·복원되는 값 자체에서 검사한다.

        Raises:
            ValueError: 댓글이 공백이거나 전달 크기 한도를 넘는 경우.
        """
        if not self.body.strip() or len(self.body.encode()) > 1048576:
            raise ValueError("Comment body must be non-empty and within its delivery limit")

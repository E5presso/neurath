"""덮어쓰지 않는 기사 원문과 정정 이유다."""

from collections.abc import Sequence
from typing import override

from spakky.core.common.mutability import immutable
from spakky.domain.models.value_object import AbstractValueObject


@immutable
class ArticleRevision(AbstractValueObject):
    """덮어쓰지 않는 기사 원문과 정정 이유다.

    Attributes:
        number: 기사 안에서 증가하는 개정 번호.
        title: 선택 조회할 짧은 제목.
        body: 해당 개정의 전체 본문.
        references: 발견의 근거 참조.
        reason: 최초 발행 또는 실제 정정 이유.
    """

    number: int
    title: str
    body: str
    references: Sequence[str]
    reason: str

    @override
    def validate(self) -> None:
        """필수 원문과 근거 및 호스트 전달 크기를 검사한다.

        Raises:
            ValueError: 원문이 비었거나 크기 한도를 넘는 경우.
        """
        if not all(value.strip() for value in (self.title, self.body, self.reason)):
            raise ValueError("Article title, body and reason must be non-empty")
        if not self.references or any(not value.strip() for value in self.references):
            raise ValueError("Article evidence references are required")
        if len(self.title) > 200 or len(self.body.encode()) > 1048576:
            raise ValueError("Article title or body exceeds its delivery limit")

"""기사의 개정·댓글·열람·작업 사용과 제목 알림을 구분하는 불변 기록이다."""

from collections.abc import Sequence
from enum import StrEnum
from typing import override
from uuid import UUID

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


@immutable
class ArticleRead:
    """전체 본문을 반환한 한 개정의 열람이다.

    Attributes:
        peer_id: 본문을 선택 조회한 피어.
        revision_number: 실제 반환한 개정.
    """

    peer_id: UUID
    revision_number: int


@immutable
class ArticleUse:
    """기사 개정을 실제 사용한다고 연결한 작업의 범위다.

    Attributes:
        task_id: 기사 내용을 사용한 태스크.
        definition_number: 사용 당시 태스크 요구 개정.
        revision_number: 사용한 기사 개정.
        peer_id: 작업 사용을 연결한 피어.
    """

    task_id: UUID
    definition_number: int
    revision_number: int
    peer_id: UUID


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

"""프로젝트 기사의 원문·개정·토론과 실제 사용 범위를 보존한다."""

from collections.abc import Sequence
from dataclasses import replace
from typing import Self, override
from uuid import UUID, uuid7

from spakky.core.common.mutability import mutable
from spakky.domain.models.aggregate_root import AbstractAggregateRoot

from neurath.domain.aggregates.peer import Peer
from neurath.domain.errors import ContextNotFound, InvalidTaskState, RevisionConflict
from neurath.domain.values.article_comment import ArticleComment
from neurath.domain.values.article_notice import ArticleNotice, ArticleNoticeStatus
from neurath.domain.values.article_read import ArticleRead
from neurath.domain.values.article_revision import ArticleRevision
from neurath.domain.values.article_use import ArticleUse


@mutable
class Article(AbstractAggregateRoot[UUID]):
    """기사가 소유하는 이력을 보존하며 태스크 성공을 판정하지 않는다.

    Attributes:
        project_id: 발견을 공유하는 프로젝트.
        author_id: 최초 발행자이며 정정 권한을 가진 실제 피어.
        revisions: 최초 발행부터 이어지는 원문 개정.
        comments: 읽은 개정에 연결된 댓글 이력.
        reads: 전체 본문을 반환한 개정별 열람.
        uses: 실제 사용한 작업·요구 개정과 기사 개정의 연결.
        notices: 활성 구독자로 확정한 개정별 제목 알림.
        revision: 저장소 낙관적 변경 버전.
    """

    project_id: UUID
    author_id: UUID
    revisions: Sequence[ArticleRevision]
    comments: Sequence[ArticleComment] = ()
    reads: Sequence[ArticleRead] = ()
    uses: Sequence[ArticleUse] = ()
    notices: Sequence[ArticleNotice] = ()
    revision: int = 1

    @classmethod
    @override
    def next_id(cls) -> UUID:
        """개정에도 유지할 기사 식별자를 생성한다.

        Returns:
            UUID: 새로운 기사 식별자.
        """
        return uuid7()

    @classmethod
    def publish(
        cls, project_id: UUID, author_id: UUID, title: str, body: str, references: Sequence[str]
    ) -> Self:
        """최초 원문과 근거를 가진 기사를 만든다.

        Args:
            project_id: 발행 프로젝트.
            author_id: 관찰한 작성자.
            title: 선택 조회할 제목.
            body: 전체 본문.
            references: 발견의 근거.

        Returns:
            Self: 아직 열람·댓글이 없는 기사.
        """
        return cls(
            uid=cls.next_id(),
            project_id=project_id,
            author_id=author_id,
            revisions=(
                ArticleRevision(
                    number=1,
                    title=title,
                    body=body,
                    references=references,
                    reason="Initial publication",
                ),
            ),
        )

    @override
    def validate(self) -> None:
        """최초 원문 개정이 없는 기사 생성을 거절한다.

        Raises:
            ValueError: 보존할 최초 원문 개정이 없는 경우.
        """
        if not self.revisions:
            raise ValueError("An article requires its original revision")

    @property
    def current(self) -> ArticleRevision:
        """현재 기사 개정의 원문을 반환한다.

        Returns:
            ArticleRevision: 가장 최근에 보존한 기사 개정.
        """
        return self.revisions[-1]

    def require_project(self, project_id: UUID) -> None:
        """다른 프로젝트에서 본문과 이력을 조회하거나 변경하지 못하게 한다.

        Args:
            project_id: 호출자의 관찰한 프로젝트.

        Raises:
            ContextNotFound: 기사가 다른 프로젝트에 속한 경우.
        """
        if self.project_id != project_id:
            raise ContextNotFound("Article belongs to another project")

    def select(self, number: int) -> ArticleRevision:
        """지정한 과거 또는 현재 개정의 전체 본문을 선택한다.

        Args:
            number: 실제 조회할 기사 개정.

        Returns:
            ArticleRevision: 해당 개정의 원문.

        Raises:
            ContextNotFound: 존재하지 않는 개정인 경우.
        """
        for item in self.revisions:
            if item.number == number:
                return item
        raise ContextNotFound("Article revision does not exist")

    def revise(
        self,
        author_id: UUID,
        expected_revision: int,
        title: str,
        body: str,
        references: Sequence[str],
        reason: str,
    ) -> None:
        """작성자와 현재 개정을 확인한 뒤 이전 원문을 남기고 정정한다.

        Args:
            author_id: 정정을 요청한 피어.
            expected_revision: 호출자가 읽은 기사 개정 번호.
            title: 정정한 제목.
            body: 정정한 전체 본문.
            references: 정정 근거.
            reason: 정정 이유.

        Raises:
            ContextNotFound: 원 작성자가 아닌 경우.
            RevisionConflict: 관찰한 기사 개정이 오래된 경우.
        """
        if author_id != self.author_id:
            raise ContextNotFound("Only the article author can revise it")
        if expected_revision != self.current.number:
            raise RevisionConflict("Article changed; read its current revision")
        self.revisions = (
            *self.revisions,
            ArticleRevision(
                number=self.current.number + 1,
                title=title,
                body=body,
                references=references,
                reason=reason,
            ),
        )

    def read(self, peer_id: UUID, number: int) -> ArticleRevision:
        """전체 반환하는 개정만 열람으로 남기며 다른 개정으로 확장하지 않는다.

        Args:
            peer_id: 본문을 요청한 피어.
            number: 실제 반환할 개정.

        Returns:
            ArticleRevision: 잘리지 않은 해당 개정의 본문.
        """
        selected = self.select(number)
        if not any(
            item.peer_id == peer_id and item.revision_number == number for item in self.reads
        ):
            self.reads = (*self.reads, ArticleRead(peer_id=peer_id, revision_number=number))
        return selected

    def comment(self, peer_id: UUID, number: int, body: str) -> None:
        """읽음이 확인된 개정에만 댓글을 붙인다.

        Args:
            peer_id: 실제 댓글 작성자.
            number: 읽고 논의한 개정.
            body: 댓글 전체 본문.

        Raises:
            InvalidTaskState: 선택 개정을 읽지 않은 경우.
        """
        if not any(
            item.peer_id == peer_id and item.revision_number == number for item in self.reads
        ):
            raise InvalidTaskState("Read this article revision before commenting")
        self.comments = (
            *self.comments,
            ArticleComment(
                number=len(self.comments) + 1,
                revision_number=number,
                peer_id=peer_id,
                body=body,
            ),
        )

    def use(self, peer_id: UUID, number: int, task_id: UUID, definition_number: int) -> None:
        """읽은 기사와 실제 사용 작업의 요구 개정을 중복 없이 연결한다.

        Args:
            peer_id: 사용을 요청한 피어.
            number: 실제 읽은 기사 개정.
            task_id: 범위를 확인한 태스크.
            definition_number: 사용 당시 요구 개정.

        Raises:
            InvalidTaskState: 사용하려는 개정의 본문을 읽지 않은 경우.
        """
        if not any(
            item.peer_id == peer_id and item.revision_number == number for item in self.reads
        ):
            raise InvalidTaskState("Read this article revision before using it")
        value = ArticleUse(
            task_id=task_id,
            definition_number=definition_number,
            revision_number=number,
            peer_id=peer_id,
        )
        if not any(
            (item.task_id, item.definition_number, item.revision_number, item.peer_id)
            == (task_id, definition_number, number, peer_id)
            for item in self.uses
        ):
            self.uses = (*self.uses, value)

    def affected_tasks(self, peer_id: UUID) -> Sequence[ArticleUse]:
        """이 피어가 사용한 옛 개정 중 현재 개정으로 다시 확인하지 않은 작업을 찾는다.

        Args:
            peer_id: 정정 영향을 확인할 실제 사용자.

        Returns:
            Sequence[ArticleUse]: 과거 원문을 보존한 중복 없는 영향 작업.
        """
        latest: dict[tuple[UUID, int], ArticleUse] = {}
        for item in self.uses:
            if item.peer_id != peer_id:
                continue
            key = (item.task_id, item.definition_number)
            previous = latest.get(key)
            if previous is None or previous.revision_number < item.revision_number:
                latest[key] = item
        return tuple(item for item in latest.values() if item.revision_number < self.current.number)

    def queue_notices(self, peers: Sequence[Peer]) -> None:
        """발행 당시 활성 구독자만 수신자로 확정한다.

        Args:
            peers: 같은 프로젝트임을 확인한 등록 피어들.
        """
        self.notices = (
            *self.notices,
            *(
                ArticleNotice(peer_id=peer.uid, revision_number=self.current.number)
                for peer in peers
                if peer.uid != self.author_id and peer.active and "newsroom" in peer.subscriptions
            ),
        )

    def consume_notices(self, peer: Peer, continuous: bool) -> bool:
        """최신 제목만 한 번 제출하고 대기·종료·구독 해제 뒤 과거 알림을 폐기한다.

        Args:
            peer: 현재 수신 활성 상태와 구독.
            continuous: 이전 관찰에서도 활성 상태였는지 여부.

        Returns:
            bool: 이번 훅에서 현재 개정 제목을 전달할 수 있는 경우.
        """
        eligible = peer.active and continuous and "newsroom" in peer.subscriptions
        notify = False
        notices: list[ArticleNotice] = []
        for item in self.notices:
            if item.peer_id != peer.uid or item.status is not ArticleNoticeStatus.PENDING:
                notices.append(item)
                continue
            status = ArticleNoticeStatus.DISCARDED
            if eligible and item.revision_number == self.current.number:
                status = ArticleNoticeStatus.SUBMITTED
                notify = True
            notices.append(replace(item, status=status))
        self.notices = tuple(notices)
        return notify

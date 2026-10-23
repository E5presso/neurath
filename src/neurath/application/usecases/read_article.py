"""선택한 개정의 전체 본문을 조회하며 출력 전에는 열람을 기록하지 않는다."""

from collections.abc import Sequence
from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.query import AbstractQuery, IAsyncQueryUseCase

from neurath.application.ports.repositories.article import IArticleRepository
from neurath.application.ports.repositories.peer import IPeerRepository
from neurath.application.ports.repositories.session import ISessionRepository
from neurath.application.ports.repositories.task import ITaskRepository
from neurath.domain.article_records import ArticleComment, ArticleRevision, ArticleUse


@immutable
class ReadArticleQuery(AbstractQuery):
    """전체 본문을 선택 조회할 피어와 실제 반환할 개정을 지정한다.

    Attributes:
        peer_id: 등록된 실제 호출 피어.
        article_id: 선택 조회할 기사.
        revision_number: 실제 읽을 기사 개정.
        task_id: 해당 개정을 실제 사용하는 작업이며 단순 열람이면 None.
    """

    peer_id: UUID
    article_id: UUID
    revision_number: int
    task_id: UUID | None = None


@immutable
class ReadArticleResult:
    """선택 개정의 전체 원문과 그 개정의 댓글을 반환한다.

    Attributes:
        article_id: 원 기사 식별자.
        author_id: 최초 원 작성자.
        current_revision: 현재 최신 기사 개정.
        content: 전체 출력할 개정이며 아직 열람을 기록하지 않음.
        comments: 해당 개정에 연결된 댓글.
        affected_tasks: 호출 피어가 실제 사용한 옛 개정의 영향 작업.
        task_definition_number: 실제 사용을 요청한 작업의 현재 요구 개정이며 없으면 None.
    """

    article_id: UUID
    author_id: UUID
    current_revision: int
    content: ArticleRevision
    comments: Sequence[ArticleComment]
    affected_tasks: Sequence[ArticleUse]
    task_definition_number: int | None


@UseCase()
class ReadArticleUseCase(IAsyncQueryUseCase[ReadArticleQuery, ReadArticleResult]):
    """기사 범위와 실제 사용 작업을 확인해 전체 출력할 개정을 조회한다."""

    def __init__(
        self,
        articles: IArticleRepository,
        peers: IPeerRepository,
        sessions: ISessionRepository,
        tasks: ITaskRepository,
    ) -> None:
        """원문과 실제 호출·사용 범위를 조회할 저장소를 주입받는다.

        Args:
            articles: 기사와 그 개정별 열람의 저장.
            peers: 호출자의 실제 호스트 주소.
            sessions: 프로젝트 소속 확인.
            tasks: 실제 사용한 작업의 현재 요구 조회.
        """
        self.articles = articles
        self.peers = peers
        self.sessions = sessions
        self.tasks = tasks

    @transactional
    @override
    async def run(self, query: ReadArticleQuery) -> ReadArticleResult:
        """본문을 자르지 않고 반환하며 프로젝트가 다른 작업의 사용 요청을 거절한다.

        Args:
            query: 선택한 기사 개정과 실제 사용 작업.

        Returns:
            ReadArticleResult: 본문과 해당 개정 댓글 및 미확인 정정 영향.
        """
        peer = await self.peers.get(query.peer_id)
        session = await self.sessions.get(peer.session_id)
        article = await self.articles.get(query.article_id)
        article.require_project(session.project_id)
        content = article.select(query.revision_number)
        definition_number = None
        if query.task_id is not None:
            task = await self.tasks.get(query.task_id)
            task.require_project(session.project_id)
            definition_number = task.definition.number
        return ReadArticleResult(
            article_id=article.uid,
            author_id=article.author_id,
            current_revision=article.current.number,
            content=content,
            comments=tuple(
                item for item in article.comments if item.revision_number == content.number
            ),
            affected_tasks=article.affected_tasks(peer.uid),
            task_definition_number=definition_number,
        )

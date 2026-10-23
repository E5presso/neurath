"""실제 읽은 개정의 댓글을 보존하며 태스크 결과를 바꾸지 않는다."""

from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.repositories.article import IArticleRepository
from neurath.application.ports.repositories.peer import IPeerRepository
from neurath.application.ports.repositories.session import ISessionRepository
from neurath.domain.aggregates.article import Article


@immutable
class CommentOnArticleCommand(AbstractCommand):
    """실제 읽은 개정의 댓글을 보존하며 태스크 결과를 바꾸지 않는다.

    Attributes:
        peer_id: 실제 댓글 작성 피어.
        article_id: 논의할 기사.
        revision_number: 읽은 기사 개정.
        body: 댓글 전체 원문.
    """

    peer_id: UUID
    article_id: UUID
    revision_number: int
    body: str


@UseCase()
class CommentOnArticleUseCase(IAsyncCommandUseCase[CommentOnArticleCommand, Article]):
    """실제 읽은 개정의 댓글을 보존하며 태스크 결과를 바꾸지 않는다."""

    def __init__(
        self, articles: IArticleRepository, peers: IPeerRepository, sessions: ISessionRepository
    ) -> None:
        """기사·작성자와 실제 프로젝트 범위의 저장소를 받는다.

        Args:
            articles: 기사와 모든 소유 이력의 저장.
            peers: 실제 피어 주소와 현재 구독.
            sessions: 피어가 속한 프로젝트 확인.
        """
        self.articles = articles
        self.peers = peers
        self.sessions = sessions

    @transactional
    @override
    async def run(self, command: CommentOnArticleCommand) -> Article:
        """실제 읽은 개정의 댓글을 보존하며 태스크 결과를 바꾸지 않는다.

        Args:
            command: 원문과 실제 호출 피어의 범위.

        Returns:
            Article: 원문과 소유 이력을 보존한 최신 기사.
        """
        peer = await self.peers.get(command.peer_id)
        session = await self.sessions.get(peer.session_id)
        article = await self.articles.get(command.article_id)
        article.require_project(session.project_id)
        article.comment(peer.uid, command.revision_number, command.body)
        return await self.articles.save(article)

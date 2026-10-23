"""기사 원문과 근거를 저장하고 활성 구독자의 제목 알림만 확정한다."""

from collections.abc import Sequence
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
class PublishArticleCommand(AbstractCommand):
    """기사 원문과 근거를 저장하고 활성 구독자의 제목 알림만 확정한다.

    Attributes:
        peer_id: 실제 발행 피어.
        title: 선택 조회할 제목.
        body: 기사 전체 본문.
        references: 발견의 근거.
    """

    peer_id: UUID
    title: str
    body: str
    references: Sequence[str]


@UseCase()
class PublishArticleUseCase(IAsyncCommandUseCase[PublishArticleCommand, Article]):
    """기사 원문과 근거를 저장하고 활성 구독자의 제목 알림만 확정한다."""

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
    async def run(self, command: PublishArticleCommand) -> Article:
        """기사 원문과 근거를 저장하고 활성 구독자의 제목 알림만 확정한다.

        Args:
            command: 원문과 실제 호출 피어의 범위.

        Returns:
            Article: 원문과 소유 이력을 보존한 최신 기사.
        """
        peer = await self.peers.get(command.peer_id)
        peer.require_active()
        session = await self.sessions.get(peer.session_id)
        article = Article.publish(
            session.project_id, peer.uid, command.title, command.body, command.references
        )
        article.queue_notices(await self.peers.find_by_project_id(session.project_id))
        return await self.articles.save(article)

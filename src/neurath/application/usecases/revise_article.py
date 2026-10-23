"""원 작성자의 기대 개정을 확인하고 정정 원문과 새 알림을 보존한다."""

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
class ReviseArticleCommand(AbstractCommand):
    """원 작성자의 기대 개정을 확인하고 정정 원문과 새 알림을 보존한다.

    Attributes:
        peer_id: 실제 정정 피어.
        article_id: 정정할 기사.
        expected_revision: 기대하는 기사 개정 번호.
        title: 새 제목.
        body: 새 전체 본문.
        references: 정정 근거.
        reason: 정정 이유.
    """

    peer_id: UUID
    article_id: UUID
    expected_revision: int
    title: str
    body: str
    references: Sequence[str]
    reason: str


@UseCase()
class ReviseArticleUseCase(IAsyncCommandUseCase[ReviseArticleCommand, Article]):
    """원 작성자의 기대 개정을 확인하고 정정 원문과 새 알림을 보존한다."""

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
    async def run(self, command: ReviseArticleCommand) -> Article:
        """원 작성자의 기대 개정을 확인하고 정정 원문과 새 알림을 보존한다.

        Args:
            command: 원문과 실제 호출 피어의 범위.

        Returns:
            Article: 원문과 소유 이력을 보존한 최신 기사.
        """
        peer = await self.peers.get(command.peer_id)
        session = await self.sessions.get(peer.session_id)
        article = await self.articles.get(command.article_id)
        article.require_project(session.project_id)
        article.revise(
            peer.uid,
            command.expected_revision,
            command.title,
            command.body,
            command.references,
            command.reason,
        )
        article.queue_notices(await self.peers.find_by_project_id(session.project_id))
        return await self.articles.save(article)

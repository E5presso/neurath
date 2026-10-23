"""같은 프로젝트 기사의 제목·개정·해당 개정 열람과 실제 작업 영향을 제한 조회한다."""

from collections.abc import Sequence
from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.query import AbstractQuery, IAsyncQueryUseCase
from spakky.plugins.sqlalchemy.persistency.session_manager import AsyncSessionManager
from sqlalchemy import func, select

from neurath.domain.article_records import ArticleUse
from neurath.domain.errors import ContextNotFound
from neurath.infrastructure.models.article import ArticleModel, ArticleRevisionModel
from neurath.infrastructure.models.peer import PeerModel
from neurath.infrastructure.models.session import SessionModel


@immutable
class ListArticlesQuery(AbstractQuery):
    """현재 피어가 선택 조회할 기사 제목 목록의 범위를 지정한다.

    Attributes:
        peer_id: 현재 등록된 피어.
        text: 제목 검색 문자열.
        after_id: 이전 페이지의 마지막 기사 식별자.
        limit: 반환할 최대 기사 개수.
    """

    peer_id: UUID
    text: str = ""
    after_id: UUID | None = None
    limit: int = 20


@immutable
class ArticleSummary:
    """전체 본문을 주입하지 않는 선택 조회 항목이다.

    Attributes:
        id: 원 기사 식별자.
        author_id: 원 작성 피어.
        title: 최신 개정의 제목.
        revision_number: 현재 기사 개정.
        seen: 현재 개정의 전체 본문을 읽었는지 여부.
        affected_tasks: 이 피어가 사용한 옛 개정의 실제 작업 참조.
    """

    id: UUID
    author_id: UUID
    title: str
    revision_number: int
    seen: bool
    affected_tasks: Sequence[ArticleUse]


@UseCase()
class ListArticlesUseCase(IAsyncQueryUseCase[ListArticlesQuery, Sequence[ArticleSummary]]):
    """제목 목록은 열람을 남기거나 외부 알림을 재전송하지 않는다."""

    def __init__(self, sessions: AsyncSessionManager) -> None:
        """조회 전용 프레임워크 세션을 받는다.

        Args:
            sessions: 현재 요청의 SQLAlchemy 조회 세션.
        """
        self.sessions = sessions

    @transactional
    @override
    async def run(self, query: ListArticlesQuery) -> Sequence[ArticleSummary]:
        """현재 프로젝트의 제목과 해당 개정의 실제 열람을 페이지로 반환한다.

        Args:
            query: 호출 피어와 검색·페이지 범위.

        Returns:
            Sequence[ArticleSummary]: 본문을 제외한 기사 목록.

        Raises:
            ValueError: 페이지 크기가 범위 밖인 경우.
            ContextNotFound: 등록되지 않은 피어를 지정한 경우.
        """
        if not 1 <= query.limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        session = self.sessions.session
        project_id = await session.scalar(
            select(SessionModel.project_id)
            .join(PeerModel, PeerModel.session_id == SessionModel.id)
            .where(PeerModel.id == query.peer_id)
        )
        if project_id is None:
            raise ContextNotFound("Peer has no observed host session")
        statement = select(ArticleModel).where(ArticleModel.project_id == project_id)
        if query.after_id is not None:
            statement = statement.where(ArticleModel.id > query.after_id)
        latest_number = (
            select(func.max(ArticleRevisionModel.number))
            .where(ArticleRevisionModel.article_id == ArticleModel.id)
            .correlate(ArticleModel)
            .scalar_subquery()
        )
        statement = statement.join(ArticleRevisionModel).where(
            ArticleRevisionModel.number == latest_number,
            ArticleRevisionModel.title.contains(query.text, autoescape=True),
        )
        rows = await session.scalars(statement.order_by(ArticleModel.id).limit(query.limit))
        results: list[ArticleSummary] = []
        for row in rows:
            article = row.to_domain()
            results.append(
                ArticleSummary(
                    id=article.uid,
                    author_id=article.author_id,
                    title=article.current.title,
                    revision_number=article.current.number,
                    seen=any(
                        item.peer_id == query.peer_id
                        and item.revision_number == article.current.number
                        for item in article.reads
                    ),
                    affected_tasks=article.affected_tasks(query.peer_id),
                )
            )
        return tuple(results)

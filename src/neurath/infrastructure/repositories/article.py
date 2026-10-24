"""기사 전체를 프레임워크 CRUD와 낙관적 잠금으로 저장한다."""

from collections.abc import Sequence
from typing import override
from uuid import UUID

from spakky.data.stereotype.repository import Repository
from spakky.plugins.sqlalchemy.persistency.repository import AbstractAsyncGenericRepository
from sqlalchemy import select

from neurath.application.ports.repositories.article import IArticleRepository
from neurath.domain.aggregates.article import Article
from neurath.domain.values.article_notice import ArticleNoticeStatus
from neurath.infrastructure.models.article import ArticleModel, ArticleNoticeModel


@Repository()
class SQLAlchemyArticleRepository(
    AbstractAsyncGenericRepository[Article, UUID], IArticleRepository
):
    """기사 매핑과 미소비 알림의 소유 기사 조회를 담당한다."""

    @override
    async def find_by_recipient_id(self, peer_id: UUID) -> Sequence[Article]:
        """미소비 알림의 원 기사를 중복 없이 조회한다.

        Args:
            peer_id: 실제 훅 수신 피어.

        Returns:
            Sequence[Article]: 해당 피어의 미소비 알림을 소유한 기사.
        """
        rows = await self._session_manager.session.scalars(
            select(ArticleModel)
            .where(
                ArticleModel.id.in_(
                    select(ArticleNoticeModel.article_id).where(
                        ArticleNoticeModel.peer_id == peer_id,
                        ArticleNoticeModel.status == ArticleNoticeStatus.PENDING.value,
                    )
                )
            )
            .order_by(ArticleModel.id)
        )
        return tuple(row.to_domain() for row in rows)

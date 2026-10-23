"""Conversation을 프레임워크 CRUD와 낙관적 잠금으로 저장한다."""

from spakky.data.stereotype.repository import Repository
from spakky.plugins.sqlalchemy.persistency.repository import AbstractAsyncGenericRepository

from neurath.application.ports.repositories.conversation import IConversationRepository
from neurath.domain.aggregates.conversation import Conversation


@Repository()
class SQLAlchemyConversationRepository(
    AbstractAsyncGenericRepository[Conversation, str], IConversationRepository
):
    """Conversation의 조회·매핑을 담당하며 상태 판단은 도메인에 맡긴다."""

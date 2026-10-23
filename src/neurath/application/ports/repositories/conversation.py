"""Conversation aggregate의 저장·범위 조회 계약이다."""

from abc import ABC
from uuid import UUID

from spakky.data.persistency.repository import IAsyncGenericRepository

from neurath.domain.aggregates.conversation import Conversation


class IConversationRepository(IAsyncGenericRepository[Conversation, UUID], ABC):
    """Conversation의 기본 CRUD와 배정 범위 조회를 제공한다."""

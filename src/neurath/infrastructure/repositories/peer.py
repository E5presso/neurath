"""Peer을 프레임워크 CRUD와 낙관적 잠금으로 저장한다."""

from collections.abc import Sequence
from typing import override

from spakky.data.stereotype.repository import Repository
from spakky.plugins.sqlalchemy.persistency.repository import AbstractAsyncGenericRepository
from sqlalchemy import select

from neurath.application.ports.repositories.peer import IPeerRepository
from neurath.domain.aggregates.peer import Peer
from neurath.infrastructure.models.peer import PeerModel


@Repository()
class SQLAlchemyPeerRepository(AbstractAsyncGenericRepository[Peer, str], IPeerRepository):
    """Peer의 조회·매핑을 담당하며 상태 판단은 도메인에 맡긴다."""

    @override
    async def find_by_session_id_and_agent_id(self, session_id: str, agent_id: str) -> Peer | None:
        """조건에 해당하는 aggregate를 조회한다.

        Args:
            session_id: 조회할 session_id 범위.
            agent_id: 조회할 agent_id 범위.

        Returns:
            Peer | None: 현재 저장된 대상이며 없으면 빈 결과.
        """
        rows = await self._session_manager.session.scalar(
            select(PeerModel).where(
                PeerModel.session_id == session_id, PeerModel.agent_id == agent_id
            )
        )
        if rows is None:
            return None
        return rows.to_domain()

    @override
    async def find_by_session_id(self, session_id: str) -> Sequence[Peer]:
        """조건에 해당하는 aggregate를 조회한다.

        Args:
            session_id: 조회할 session_id 범위.

        Returns:
            Sequence[Peer]: 현재 저장된 대상이며 없으면 빈 결과.
        """
        rows = await self._session_manager.session.scalars(
            select(PeerModel).where(PeerModel.session_id == session_id)
        )
        return tuple(row.to_domain() for row in rows)

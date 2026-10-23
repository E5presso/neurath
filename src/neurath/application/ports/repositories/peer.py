"""Peer aggregate의 저장·범위 조회 계약이다."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from uuid import UUID

from spakky.data.persistency.repository import IAsyncGenericRepository

from neurath.domain.aggregates.peer import Peer


class IPeerRepository(IAsyncGenericRepository[Peer, UUID], ABC):
    """Peer의 기본 CRUD와 배정 범위 조회를 제공한다."""

    @abstractmethod
    async def find_by_session_id_and_agent_id(self, session_id: UUID, agent_id: str) -> Peer | None:
        """조건에 해당하는 aggregate를 조회한다.

        Args:
            session_id: 조회할 session_id 범위.
            agent_id: 조회할 agent_id 범위.

        Returns:
            Peer | None: 현재 저장된 대상이며 없으면 빈 결과.

        Raises:
            NotImplementedError: 저장·실행 어댑터가 이 계약을 구현하지 않은 경우.
        """
        raise NotImplementedError

    @abstractmethod
    async def find_by_session_id(self, session_id: UUID) -> Sequence[Peer]:
        """조건에 해당하는 aggregate를 조회한다.

        Args:
            session_id: 조회할 session_id 범위.

        Returns:
            Sequence[Peer]: 현재 저장된 대상이며 없으면 빈 결과.

        Raises:
            NotImplementedError: 저장·실행 어댑터가 이 계약을 구현하지 않은 경우.
        """
        raise NotImplementedError

    @abstractmethod
    async def find_by_project_id(self, project_id: UUID) -> Sequence[Peer]:
        """발행에 필요한 같은 프로젝트의 피어 aggregate를 조회한다.

        Args:
            project_id: 발행할 프로젝트 범위.

        Returns:
            Sequence[Peer]: 관찰한 해당 프로젝트의 피어.

        Raises:
            NotImplementedError: 저장 어댑터가 계약을 구현하지 않은 경우.
        """
        raise NotImplementedError

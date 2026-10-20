"""Execution 기본 CRUD를 재사용하고 현재 식별자 조회만 추가한다."""

from abc import ABC, abstractmethod

from spakky.data.persistency.repository import IGenericRepository

from neurath.domain.aggregates.execution import Execution


class IExecutionRepository(IGenericRepository[Execution, str], ABC):
    """세션과 실제 자식 식별자로 실행 상태를 조회한다."""

    @abstractmethod
    def find(self, session_id: str, agent_id: str) -> Execution | None:
        """세션과 실제 자식 식별자로 실행 상태를 조회한다.

        Args:
            session_id: 조회할 호스트 세션 식별자.
            agent_id: 조회할 네이티브 자식 식별자.

        Returns:
            Execution | None: 일치하는 기록이며 없으면 None.

        Raises:
            NotImplementedError: 구체 저장소가 조회 계약을 구현하지 않은 경우.
        """
        raise NotImplementedError

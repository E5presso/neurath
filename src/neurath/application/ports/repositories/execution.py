"""호스트 실행 상태의 기본 Aggregate 저장 계약을 제공한다."""

from abc import ABC, abstractmethod
from collections.abc import Sequence

from spakky.data.persistency.repository import IAsyncGenericRepository

from neurath.domain.aggregates.execution import Execution


class IExecutionRepository(IAsyncGenericRepository[Execution, str], ABC):
    """실제 턴·중단 상태·Stop 관찰을 가진 실행의 식별자 조회와 저장을 프레임워크 기본 계약으로 제공한다."""

    @abstractmethod
    async def find_by_session_id_and_agent_id(
        self, session_id: str, agent_id: str
    ) -> Execution | None:
        """현재 세션과 자식 식별자에 연결된 실행 aggregate를 찾는다.

        Args:
            session_id: 실행을 소유한 세션.
            agent_id: 실제 자식 식별자이며 루트는 빈 문자열.

        Returns:
            Execution | None: 해당 세션·에이전트의 실행이며 아직 관찰되지 않았으면 None.

        Raises:
            NotImplementedError: 저장 어댑터가 조회 계약을 구현하지 않은 경우.
        """
        raise NotImplementedError

    @abstractmethod
    async def find_by_session_id(self, session_id: str) -> Sequence[Execution]:
        """인수 확인에 필요한 범위의 실행 또는 작성 기록을 조회한다.

        Args:
            session_id: 조회할 소유 범위의 ID.

        Returns:
            Sequence[Execution]: 상태를 생략하지 않은 aggregate 목록.

        Raises:
            NotImplementedError: 추상 조회를 직접 호출한 경우.
        """
        raise NotImplementedError

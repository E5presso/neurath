"""호스트 실행 상태의 기본 Aggregate 저장 계약을 제공한다."""

from collections.abc import Sequence
from typing import override

from spakky.data.stereotype.repository import Repository
from spakky.plugins.sqlalchemy.persistency.repository import AbstractAsyncGenericRepository
from sqlalchemy import select

from neurath.application.ports.repositories.execution import IExecutionRepository
from neurath.domain.aggregates.execution import Execution
from neurath.infrastructure.models.execution import ExecutionModel


@Repository()
class SQLAlchemyExecutionRepository(
    AbstractAsyncGenericRepository[Execution, str], IExecutionRepository
):
    """실제 턴·중단 상태·Stop 관찰을 가진 실행를 표준 SQLAlchemy 매핑·CRUD·낙관적 잠금으로 저장한다."""

    @override
    async def find_by_session_id_and_agent_id(
        self, session_id: str, agent_id: str
    ) -> Execution | None:
        """현재 세션과 자식 식별자에 연결된 실행 aggregate를 찾는다.

        Args:
            session_id: 실행을 소유한 세션.
            agent_id: 실제 자식 식별자이며 루트는 빈 문자열.

        Returns:
            Execution | None: 해당 세션·에이전트의 실행이며 아직 관찰되지 않았으면 None.
        """
        record = await self._session_manager.session.scalar(
            select(ExecutionModel).where(
                ExecutionModel.session_id == session_id, ExecutionModel.agent_id == agent_id
            )
        )
        if record is None:
            return None
        return record.to_domain()

    @override
    async def find_by_session_id(self, session_id: str) -> Sequence[Execution]:
        """소유 범위의 상태 기록을 인수 판단용 aggregate로 조회한다.

        Args:
            session_id: 조회할 소유 범위의 ID.

        Returns:
            Sequence[Execution]: 저장된 현재 상태 목록.
        """
        rows = await self._session_manager.session.scalars(
            select(ExecutionModel).where(ExecutionModel.session_id == session_id)
        )
        return tuple(row.to_domain() for row in rows)

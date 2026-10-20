"""Execution의 기본 저장·잠금은 프레임워크에 위임한다."""

from typing import override

from spakky.data.stereotype.repository import Repository
from spakky.plugins.sqlalchemy.persistency.repository import AbstractGenericRepository
from sqlalchemy import select

from neurath.application.ports.repositories.execution import IExecutionRepository
from neurath.domain.aggregates.execution import Execution
from neurath.infrastructure.models.execution import ExecutionModel


@Repository()
class ExecutionRepository(AbstractGenericRepository[Execution, str], IExecutionRepository):
    """세션과 실제 자식 식별자로 실행 상태를 조회한다."""

    @override
    def find(self, session_id: str, agent_id: str) -> Execution | None:
        """세션과 실제 자식 식별자로 실행 상태를 조회한다.

        Args:
            session_id: 조회할 호스트 세션 식별자.
            agent_id: 조회할 네이티브 자식 식별자.

        Returns:
            Execution | None: 일치하는 기록이며 없으면 None.
        """
        record = self._session_manager.session.scalar(
            select(ExecutionModel).where(
                ExecutionModel.session_id == session_id, ExecutionModel.agent_id == agent_id
            )
        )
        if record is None:
            return None
        return record.to_domain()

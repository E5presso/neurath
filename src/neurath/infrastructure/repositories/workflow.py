"""워크플로우 실행의 기본 Aggregate 저장 계약을 제공한다."""

from typing import override
from uuid import UUID

from spakky.data.stereotype.repository import Repository
from spakky.plugins.sqlalchemy.persistency.repository import AbstractAsyncGenericRepository
from sqlalchemy import select

from neurath.application.ports.repositories.workflow import IWorkflowRepository
from neurath.domain.aggregates.workflow import WorkflowRun
from neurath.infrastructure.models.workflow import WorkflowModel


@Repository()
class SQLAlchemyWorkflowRepository(
    AbstractAsyncGenericRepository[WorkflowRun, UUID], IWorkflowRepository
):
    """단계 정의 개정과 시도 결과를 소유하는 워크플로우를 표준 SQLAlchemy 매핑·CRUD·낙관적 잠금으로 저장한다."""

    @override
    async def find_by_task_id(self, task_id: UUID) -> WorkflowRun | None:
        """태스크에 연결한 워크플로우 aggregate를 조회한다.

        Args:
            task_id: 절차를 소유한 태스크.

        Returns:
            WorkflowRun | None: 태스크에 연결한 절차와 시도 이력이며 연결된 절차가 없으면 None.
        """
        record = await self._session_manager.session.scalar(
            select(WorkflowModel).where(WorkflowModel.task_id == task_id)
        )
        if record is None:
            return None
        return record.to_domain()

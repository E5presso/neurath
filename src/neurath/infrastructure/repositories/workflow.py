"""워크플로의 소유 관계를 기본 저장소로 저장하고 태스크 연결을 조회한다."""

from typing import override

from spakky.data.stereotype.repository import Repository
from spakky.plugins.sqlalchemy.persistency.repository import AbstractGenericRepository
from sqlalchemy import select

from neurath.application.ports.repositories.workflow import IWorkflowRepository
from neurath.domain.aggregates.workflow import WorkflowRun
from neurath.infrastructure.models.workflow import WorkflowModel


@Repository()
class SQLAlchemyWorkflowRepository(
    AbstractGenericRepository[WorkflowRun, str], IWorkflowRepository
):
    """기본 CRUD를 재사용하며 태스크에 연결한 run의 전체 이력을 조회한다."""

    @override
    def find_by_task(self, task_id: str) -> WorkflowRun | None:
        """고유 태스크 참조로 run을 찾아 ORM과 분리된 도메인 객체로 반환한다.

        Args:
            task_id: run을 찾을 태스크 ID.

        Returns:
            WorkflowRun | None: 정의·시도를 포함한 run. 없으면 None.
        """
        record = self._session_manager.session.scalar(
            select(WorkflowModel).where(WorkflowModel.task_id == task_id)
        )
        return None if record is None else record.to_domain()

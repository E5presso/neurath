"""Task의 기본 저장은 상속하고 프로젝트 목록만 조회한다."""

from typing import override

from spakky.data.stereotype.repository import Repository
from spakky.plugins.sqlalchemy.persistency.repository import AbstractGenericRepository
from sqlalchemy import select

from neurath.application.ports.repositories.task import ITaskRepository
from neurath.domain.aggregates.task import Task
from neurath.infrastructure.models.task import TaskModel


@Repository()
class TaskRepository(AbstractGenericRepository[Task, str], ITaskRepository):
    """프레임워크 CRUD를 재구현하지 않는 저장소다."""

    @override
    def list(self, project_id: str) -> tuple[Task, ...]:
        """프로젝트 범위의 모든 현재 레코드를 조회한다.

        Args:
            project_id: 조회 프로젝트.

        Returns:
            tuple[Task, ...]: 원장과 같은 전체 자료.
        """
        records = self._session_manager.session.scalars(
            select(TaskModel)
            .where(TaskModel.project_id == project_id)
            .order_by(TaskModel.created_at, TaskModel.id)
        ).all()
        return tuple(record.to_domain() for record in records)

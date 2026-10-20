"""Task의 기본 저장은 상속하고 프로젝트 목록만 조회한다."""

from collections.abc import Sequence
from typing import override

from spakky.data.stereotype.repository import Repository
from spakky.plugins.sqlalchemy.persistency.repository import AbstractGenericRepository
from sqlalchemy import select

from neurath.application.ports.repositories.task import ITaskRepository
from neurath.domain.aggregates.task import Task
from neurath.infrastructure.models.task import TaskModel


@Repository()
class SQLAlchemyTaskRepository(AbstractGenericRepository[Task, str], ITaskRepository):
    """태스크을 SQLite에 매핑하고 프로젝트 전체 목록을 도메인 객체로 조회한다."""

    @override
    def list(self, project_id: str) -> Sequence[Task]:
        """프로젝트의 태스크을 생성 시각·ID 순으로 조회해 tuple로 반환한다.

        Args:
            project_id: 조회 범위를 제한할 프로젝트 ID.

        Returns:
            Sequence[Task]: ORM 객체와 분리된 전체 태스크 목록. 없으면 빈 tuple.
        """
        records = self._session_manager.session.scalars(
            select(TaskModel)
            .where(TaskModel.project_id == project_id)
            .order_by(TaskModel.created_at, TaskModel.id)
        ).all()
        return tuple(record.to_domain() for record in records)

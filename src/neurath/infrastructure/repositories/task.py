"""태스크 원장의 기본 Aggregate 저장 계약을 제공한다."""

from collections.abc import Sequence
from typing import override
from uuid import UUID

from spakky.data.stereotype.repository import Repository
from spakky.plugins.sqlalchemy.persistency.repository import AbstractAsyncGenericRepository
from sqlalchemy import select

from neurath.application.ports.repositories.task import ITaskRepository
from neurath.domain.aggregates.task import Task
from neurath.infrastructure.models.task import TaskModel


@Repository()
class SQLAlchemyTaskRepository(AbstractAsyncGenericRepository[Task, UUID], ITaskRepository):
    """요구 개정·실행 시도·외부 대기를 소유하는 태스크를 표준 SQLAlchemy 매핑·CRUD·낙관적 잠금으로 저장한다."""

    @override
    async def find_by_project_id(self, project_id: UUID) -> Sequence[Task]:
        """의존 관계와 실행 가능성을 검증할 프로젝트의 태스크들을 읽는다.

        Args:
            project_id: 의존 관계 검사의 프로젝트 범위.

        Returns:
            Sequence[Task]: 완료 상태를 포함한 프로젝트의 모든 태스크이며 생성 시각·ID 순서로 반환한다.
        """
        records = (
            await self._session_manager.session.scalars(
                select(TaskModel)
                .where(TaskModel.project_id == project_id)
                .order_by(TaskModel.created_at, TaskModel.id)
            )
        ).all()
        return tuple(record.to_domain() for record in records)

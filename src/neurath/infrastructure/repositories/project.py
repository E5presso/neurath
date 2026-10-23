"""프로젝트와 소유 위치의 기본 Aggregate 저장 계약을 제공한다."""

from typing import override
from uuid import UUID

from spakky.data.stereotype.repository import Repository
from spakky.plugins.sqlalchemy.persistency.repository import AbstractAsyncGenericRepository
from sqlalchemy import select

from neurath.application.ports.repositories.project import IProjectRepository
from neurath.domain.aggregates.project import Project, ProjectLocation
from neurath.infrastructure.models.project import ProjectLocationModel, ProjectModel


@Repository()
class SQLAlchemyProjectRepository(
    AbstractAsyncGenericRepository[Project, UUID], IProjectRepository
):
    """프로젝트의 위치 값들을 포함한 aggregate를 표준 SQLAlchemy 매핑·CRUD·낙관적 잠금으로 저장한다."""

    @override
    async def find_by_location(self, location: ProjectLocation) -> Project | None:
        """위치 값의 현재 소유 프로젝트를 조회한다.

        Args:
            location: 도메인이 식별한 폴더 또는 Git 위치.

        Returns:
            Project | None: 지정한 위치의 소유 프로젝트이며 등록된 위치가 없으면 None.
        """
        record = await self._session_manager.session.scalar(
            select(ProjectModel)
            .join(ProjectModel.locations)
            .where(
                ProjectLocationModel.kind == location.kind.value,
                ProjectLocationModel.path == location.path,
            )
        )
        if record is None:
            return None
        return record.to_domain()

"""프레임워크의 기본 CRUD를 재사용하고 프로젝트 위치 조회만 구현한다."""

from typing import override

from spakky.core.pod.annotations.pod import Pod
from spakky.data.stereotype.repository import Repository
from spakky.plugins.sqlalchemy.persistency.repository import AbstractAsyncGenericRepository
from sqlalchemy import select

from neurath.application.ports.repositories.project import IProjectRepository
from neurath.domain.aggregates.project import Project, ProjectLocation
from neurath.infrastructure.models.project import ProjectLocationModel, ProjectModel


@Repository(scope=Pod.Scope.CONTEXT)
class SQLAlchemyProjectRepository(AbstractAsyncGenericRepository[Project, str], IProjectRepository):
    """기본 조회·저장·삭제는 상속하고 위치 소유 조회만 확장한다."""

    @override
    async def find_by_location(self, location: ProjectLocation) -> Project | None:
        """위치 값을 소유하는 프로젝트 전체를 조회한다.

        Args:
            location: 소유 프로젝트를 조회할 위치 값.

        Returns:
            Project | None: 해당 위치의 소유자이며 없으면 None.
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

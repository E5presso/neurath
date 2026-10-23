"""프로젝트와 소유 위치의 기본 Aggregate 저장 계약을 제공한다."""

from abc import ABC, abstractmethod
from uuid import UUID

from spakky.data.persistency.repository import IAsyncGenericRepository

from neurath.domain.aggregates.project import Project, ProjectLocation


class IProjectRepository(IAsyncGenericRepository[Project, UUID], ABC):
    """프로젝트의 위치 값들을 포함한 aggregate의 식별자 조회와 저장을 프레임워크 기본 계약으로 제공한다."""

    @abstractmethod
    async def find_by_location(self, location: ProjectLocation) -> Project | None:
        """위치 값의 현재 소유 프로젝트를 조회한다.

        Args:
            location: 도메인이 식별한 폴더 또는 Git 위치.

        Returns:
            Project | None: 지정한 위치의 소유 프로젝트이며 등록된 위치가 없으면 None.

        Raises:
            NotImplementedError: 저장 어댑터가 조회 계약을 구현하지 않은 경우.
        """
        raise NotImplementedError

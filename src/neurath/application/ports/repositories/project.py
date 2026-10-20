"""프로젝트 기본 CRUD는 프레임워크 계약을 상속하고 위치 조회만 추가한다."""

from abc import ABC, abstractmethod

from spakky.data.persistency.repository import IGenericRepository

from neurath.domain.aggregates.project import Project, ProjectLocation


class IProjectRepository(IGenericRepository[Project, str], ABC):
    """기본 저장 계약을 확장하여 위치 값의 소유 프로젝트를 찾는다."""

    @abstractmethod
    def find_by_location(self, location: ProjectLocation) -> Project | None:
        """주어진 위치 값을 소유하는 프로젝트를 조회한다.

        Args:
            location: 소유 프로젝트를 찾을 위치 값.

        Returns:
            Project | None: 위치의 기존 소유자이며 없으면 None.
        """
        ...

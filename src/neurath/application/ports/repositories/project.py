"""프로젝트 aggregate 전체를 조회하고 저장하는 명시적 계약이다."""

from abc import ABC, abstractmethod

from neurath.domain.aggregates.project import Project, ProjectLocation


class IProjectRepository(ABC):
    """식별 정책 없이 프로젝트와 그 소유 위치를 함께 조회·저장한다."""

    @abstractmethod
    def get(self, project_id: str) -> Project:
        """식별자에 해당하는 기존 프로젝트 전체를 조회한다.

        Args:
            project_id: 조회할 프로젝트의 안정적인 식별자.

        Returns:
            Project: 저장된 프로젝트와 소유 위치 값들.

        Raises:
            NotImplementedError: 구현 없이 추상 포트를 호출한 경우.
        """
        raise NotImplementedError

    @abstractmethod
    def find_by_location(self, location: ProjectLocation) -> Project | None:
        """지정한 위치 값을 소유하는 프로젝트를 조회한다.

        Args:
            location: 소유 프로젝트를 찾을 위치 값.

        Returns:
            Project | None: 위치의 기존 소유자이며 없으면 None.

        Raises:
            NotImplementedError: 구현 없이 추상 포트를 호출한 경우.
        """
        raise NotImplementedError

    @abstractmethod
    def save(self, project: Project) -> Project:
        """신규·기존 프로젝트와 모든 소유 위치를 현재 트랜잭션에 저장한다.

        Args:
            project: 도메인 규칙을 적용한 프로젝트 aggregate.

        Returns:
            Project: 저장된 프로젝트와 소유 위치 값들.

        Raises:
            NotImplementedError: 구현 없이 추상 포트를 호출한 경우.
        """
        raise NotImplementedError

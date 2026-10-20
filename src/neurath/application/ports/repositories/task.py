"""Task 기본 CRUD를 상속하고 프로젝트 목록 조회만 확장한다."""

from abc import ABC, abstractmethod
from collections.abc import Sequence

from spakky.data.persistency.repository import IGenericRepository

from neurath.domain.aggregates.task import Task


class ITaskRepository(IGenericRepository[Task, str], ABC):
    """기본 저장 계약과 프로젝트별 전체 목록을 제공한다."""

    @abstractmethod
    def list(self, project_id: str) -> Sequence[Task]:
        """같은 프로젝트의 현재 전체 자료를 조회한다.

        Args:
            project_id: 조회 프로젝트.

        Returns:
            Sequence[Task]: 해당 프로젝트의 모든 자료.

        Raises:
            NotImplementedError: 구체 어댑터가 목록 조회를 구현하지 않은 경우.
        """
        raise NotImplementedError

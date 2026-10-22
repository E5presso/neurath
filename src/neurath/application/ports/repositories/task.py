"""태스크 원장의 기본 Aggregate 저장 계약을 제공한다."""

from abc import ABC, abstractmethod
from collections.abc import Sequence

from spakky.data.persistency.repository import IAsyncGenericRepository

from neurath.domain.aggregates.task import Task


class ITaskRepository(IAsyncGenericRepository[Task, str], ABC):
    """요구 개정·실행 시도·외부 대기를 소유하는 태스크의 식별자 조회와 저장을 프레임워크 기본 계약으로 제공한다."""

    @abstractmethod
    async def find_by_project_id(self, project_id: str) -> Sequence[Task]:
        """의존 관계와 실행 가능성을 검증할 프로젝트의 태스크들을 읽는다.

        Args:
            project_id: 의존 관계 검사의 프로젝트 범위.

        Returns:
            Sequence[Task]: 완료 상태를 포함한 프로젝트의 모든 태스크이며 생성 시각·ID 순서로 반환한다.

        Raises:
            NotImplementedError: 저장 어댑터가 조회 계약을 구현하지 않은 경우.
        """
        raise NotImplementedError

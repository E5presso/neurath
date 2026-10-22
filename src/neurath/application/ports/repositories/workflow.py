"""워크플로우 실행의 기본 Aggregate 저장 계약을 제공한다."""

from abc import ABC, abstractmethod

from spakky.data.persistency.repository import IAsyncGenericRepository

from neurath.domain.aggregates.workflow import WorkflowRun


class IWorkflowRepository(IAsyncGenericRepository[WorkflowRun, str], ABC):
    """단계 정의 개정과 시도 결과를 소유하는 워크플로우의 식별자 조회와 저장을 프레임워크 기본 계약으로 제공한다."""

    @abstractmethod
    async def find_by_task_id(self, task_id: str) -> WorkflowRun | None:
        """태스크에 연결한 워크플로우 aggregate를 조회한다.

        Args:
            task_id: 절차를 소유한 태스크.

        Returns:
            WorkflowRun | None: 태스크에 연결한 절차와 시도 이력이며 연결된 절차가 없으면 None.

        Raises:
            NotImplementedError: 저장 어댑터가 조회 계약을 구현하지 않은 경우.
        """
        raise NotImplementedError

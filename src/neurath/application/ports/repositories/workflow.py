"""워크플로 기본 CRUD와 태스크별 선택 절차 조회 계약을 정의한다."""

from abc import ABC, abstractmethod

from spakky.data.persistency.repository import IAsyncGenericRepository

from neurath.domain.aggregates.workflow import WorkflowRun


class IWorkflowRepository(IAsyncGenericRepository[WorkflowRun, str], ABC):
    """run 전체를 저장하고 태스크에 연결한 절차를 조회한다."""

    @abstractmethod
    async def find_by_task(self, task_id: str) -> WorkflowRun | None:
        """태스크가 선택한 절차를 정의·시도 이력과 함께 찾는다.

        Args:
            task_id: 절차를 선택한 태스크 ID.

        Returns:
            WorkflowRun | None: 연결된 run. 절차를 선택하지 않았다면 None.

        Raises:
            NotImplementedError: 구체 저장소가 조회를 구현하지 않은 경우.
        """
        raise NotImplementedError

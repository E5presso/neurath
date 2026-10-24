"""감시 작업이 공유하는 현재 원장·소유 실행 대조 계약이다."""

from abc import ABC, abstractmethod
from uuid import UUID

from neurath.domain.aggregates.task import Task
from neurath.domain.values.task_monitor import TaskMonitor


class IMonitorContextService(ABC):
    """호출자의 트랜잭션에서 감시 소유 범위와 최신 취소를 대조한다."""

    @abstractmethod
    async def load(
        self,
        *,
        project_id: UUID,
        session_id: UUID,
        task_id: UUID,
        monitor_number: int,
        execution_id: UUID,
        generation: int,
    ) -> tuple[Task, TaskMonitor, bool]:
        """현재 기록을 읽고 도메인에 범위·소유 검증과 취소 반영을 요청한다.

        변경한 Task는 호출한 유스케이스가 저장한다. 구현체는 별도 트랜잭션을
        시작하거나 커밋하지 않으며 외부 관찰·알림도 실행하지 않는다.

        Args:
            project_id: 요청한 프로젝트.
            session_id: 현재 소유 세션.
            task_id: 외부 대기를 소유한 태스크.
            monitor_number: 대조할 감시 순번.
            execution_id: 감시 자원의 소유 실행.
            generation: 조회 시 확인한 자원 세대.

        Returns:
            tuple[Task, TaskMonitor, bool]: 현재 태스크·대조한 감시와 새 관찰·알림 허용 여부.

        Raises:
            NotImplementedError: 어댑터가 계약을 구현하지 않은 경우.
        """
        raise NotImplementedError

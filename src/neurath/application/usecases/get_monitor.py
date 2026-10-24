"""태스크 감시·정확한 사건·실제 관찰·필요한 조작을 조회한다."""

from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.query import AbstractQuery, IAsyncQueryUseCase

from neurath.application.ports.repositories.task import ITaskRepository
from neurath.domain.values.task_monitor import TaskMonitor


@immutable
class GetMonitorQuery(AbstractQuery):
    """현재 소유 범위에서 정확한 감시 이력을 선택한다.

    Attributes:
        project_id: 조회할 프로젝트.
        session_id: 현재 작업 소유 세션.
        task_id: 원 외부 대기를 가진 태스크.
        monitor_number: 정확한 감시 순번.
    """

    project_id: UUID
    session_id: UUID
    task_id: UUID
    monitor_number: int


@UseCase()
class GetMonitorUseCase(IAsyncQueryUseCase[GetMonitorQuery, TaskMonitor]):
    """조회·재연결은 새 관찰·제출·실행을 만들지 않는다."""

    def __init__(self, tasks: ITaskRepository) -> None:
        """소유한 감시 이력을 읽을 원장을 받는다.

        Args:
            tasks: 감시·사건·알림 실패를 포함한 원장 조회.
        """
        self.tasks = tasks

    @transactional
    @override
    async def run(self, query: GetMonitorQuery) -> TaskMonitor:
        """감시의 첫 관찰·현재 상태·사건·실패와 잔여 예산을 반환한다.

        Args:
            query: 조회할 정확한 태스크·감시와 현재 소유 범위.

        Returns:
            TaskMonitor: 부작용 없이 읽은 감시 이력.
        """
        task = await self.tasks.get(query.task_id)
        task.require_scope(query.project_id, query.session_id)
        return task.monitor(query.monitor_number)

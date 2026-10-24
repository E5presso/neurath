"""현재 원장·실행·자원 세대가 일치해야 하는 감시 작업이다."""

from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.repositories.task import ITaskRepository
from neurath.application.ports.services.monitor_context import IMonitorContextService
from neurath.domain.enums.liveness import Liveness
from neurath.domain.values.task_monitor import TaskMonitor


@immutable
class RecoverMonitorCommand(AbstractCommand):
    """현재 원장·실행·자원 세대가 일치해야 하는 감시 작업이다.

    Attributes:
        project_id: 태스크의 프로젝트.
        session_id: 현재 소유 세션.
        task_id: 외부 의존을 소유한 태스크.
        monitor_number: 정확한 감시 순번.
        execution_id: 현재 자원 소유 실행.
        generation: 조회 시 확인한 자원 세대.
        poll_id: 실제 종료를 관찰한 정확한 자원.
        liveness: 관찰한 자원의 생존 상태.
    """

    project_id: UUID
    session_id: UUID
    task_id: UUID
    monitor_number: int
    execution_id: UUID
    generation: int
    poll_id: UUID
    liveness: Liveness


@UseCase()
class RecoverMonitorUseCase(IAsyncCommandUseCase[RecoverMonitorCommand, TaskMonitor]):
    """실제 자원 종료를 현재 소유 세대와 비교하여 복구한다."""

    def __init__(self, tasks: ITaskRepository, context: IMonitorContextService) -> None:
        """태스크 저장소와 감시 범위 대조 서비스를 주입받는다.

        Args:
            tasks: 자원 종료·새 세대·남은 예산 저장.
            context: 감시 범위·자원 소유·최신 취소를 대조한다.
        """
        self.tasks = tasks
        self.context = context

    @transactional
    @override
    async def run(self, command: RecoverMonitorCommand) -> TaskMonitor:
        """종료한 자원만 해제하며 취소를 해제하거나 잔여 예산을 늘리지 않는다.

        Args:
            command: 정확한 자원과 실제 종료 관찰.

        Returns:
            TaskMonitor: 현재 취소와 새 세대를 보존한 감시.
        """
        task, monitor, _ = await self.context.load(
            project_id=command.project_id,
            session_id=command.session_id,
            task_id=command.task_id,
            monitor_number=command.monitor_number,
            execution_id=command.execution_id,
            generation=command.generation,
        )
        monitor = monitor.recover(command.poll_id, command.liveness)
        task.update_monitor(monitor)
        await self.tasks.save(task)
        return monitor

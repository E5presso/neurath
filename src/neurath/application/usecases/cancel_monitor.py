"""현재 원장·실행·자원 세대가 일치해야 하는 감시 작업이다."""

from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.repositories.execution import IExecutionRepository
from neurath.application.ports.repositories.task import ITaskRepository
from neurath.application.services.monitor_context import load_monitor
from neurath.domain.values.task_monitor import TaskMonitor


@immutable
class CancelMonitorCommand(AbstractCommand):
    """현재 원장·실행·자원 세대가 일치해야 하는 감시 작업이다.

    Attributes:
        project_id: 태스크의 프로젝트.
        session_id: 현재 소유 세션.
        task_id: 외부 의존을 소유한 태스크.
        monitor_number: 정확한 감시 순번.
        execution_id: 현재 자원 소유 실행.
        generation: 조회 시 확인한 자원 세대.
    """

    project_id: UUID
    session_id: UUID
    task_id: UUID
    monitor_number: int
    execution_id: UUID
    generation: int


@UseCase()
class CancelMonitorUseCase(IAsyncCommandUseCase[CancelMonitorCommand, TaskMonitor]):
    """명시적인 감시 취소를 현재 태스크에 보존한다."""

    def __init__(self, tasks: ITaskRepository, executions: IExecutionRepository) -> None:
        """현재 원장과 실행 저장소를 받는다.

        Args:
            tasks: 취소 상태와 남은 사건 저장.
            executions: 현재 자원 소유 대조.
        """
        self.tasks = tasks
        self.executions = executions

    @transactional
    @override
    async def run(self, command: CancelMonitorCommand) -> TaskMonitor:
        """감시만 중지하고 태스크·원 대기·미확인 자원은 보존한다.

        Args:
            command: 취소할 정확한 감시.

        Returns:
            TaskMonitor: 취소와 미확인 자원을 포함한 감시.
        """
        task, monitor, _ = await load_monitor(
            self.tasks,
            self.executions,
            project_id=command.project_id,
            session_id=command.session_id,
            task_id=command.task_id,
            monitor_number=command.monitor_number,
            execution_id=command.execution_id,
            generation=command.generation,
        )
        monitor = monitor.cancel("Monitoring explicitly cancelled")
        task.update_monitor(monitor)
        await self.tasks.save(task)
        return monitor

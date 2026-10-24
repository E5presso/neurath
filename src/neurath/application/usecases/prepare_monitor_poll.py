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
class PrepareMonitorPollCommand(AbstractCommand):
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
class PrepareMonitorPollUseCase(
    IAsyncCommandUseCase[PrepareMonitorPollCommand, TaskMonitor | None]
):
    """관찰의 중복 실행을 막는 자원과 예산을 먼저 커밋한다."""

    def __init__(self, tasks: ITaskRepository, executions: IExecutionRepository) -> None:
        """원장과 소유 실행 저장소를 받는다.

        Args:
            tasks: 감시 예약과 잔여 예산 저장.
            executions: 현재 취소·종료 확인.
        """
        self.tasks = tasks
        self.executions = executions

    @transactional
    @override
    async def run(self, command: PrepareMonitorPollCommand) -> TaskMonitor | None:
        """현재 자원만 한 번 예약하며 중복·취소·예산 소진에는 외부 작업을 만들지 않는다.

        Args:
            command: 현재 원장과 자원 소유 세대.

        Returns:
            TaskMonitor | None: 새 예약 또는 새 실행이 없는 경우 None.
        """
        task, monitor, runnable = await load_monitor(
            self.tasks,
            self.executions,
            project_id=command.project_id,
            session_id=command.session_id,
            task_id=command.task_id,
            monitor_number=command.monitor_number,
            execution_id=command.execution_id,
            generation=command.generation,
        )
        updated = monitor.begin_poll() if runnable else monitor
        task.update_monitor(updated)
        await self.tasks.save(task)
        return updated if monitor.poll_id is None and updated.poll_id is not None else None

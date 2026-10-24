"""현재 원장·실행·자원 세대가 일치해야 하는 감시 작업이다."""

from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.repositories.task import ITaskRepository
from neurath.application.ports.services.monitor_context import IMonitorContextService
from neurath.domain.values.task_monitor import NoticeStatus, TaskMonitor


@immutable
class RecordMonitorNoticeCommand(AbstractCommand):
    """현재 원장·실행·자원 세대가 일치해야 하는 감시 작업이다.

    Attributes:
        project_id: 태스크의 프로젝트.
        session_id: 현재 소유 세션.
        task_id: 외부 의존을 소유한 태스크.
        monitor_number: 정확한 감시 순번.
        execution_id: 현재 자원 소유 실행.
        generation: 조회 시 확인한 자원 세대.
        event_number: 조회한 정확한 변화 사건의 순번.
        attempt: 결과를 관찰한 제출 시도.
        status: 제출·실패 또는 실제 전달 확인.
        error: 실패 사유와 필요한 조작.
    """

    project_id: UUID
    session_id: UUID
    task_id: UUID
    monitor_number: int
    execution_id: UUID
    generation: int
    event_number: int
    attempt: int
    status: NoticeStatus
    error: str = ""


@UseCase()
class RecordMonitorNoticeUseCase(IAsyncCommandUseCase[RecordMonitorNoticeCommand, TaskMonitor]):
    """외부 제출 결과와 확인 가능한 실제 전달을 원 사건에 저장한다."""

    def __init__(self, tasks: ITaskRepository, context: IMonitorContextService) -> None:
        """태스크 저장소와 감시 범위 대조 서비스를 주입받는다.

        Args:
            tasks: 원 사건과 제출 실패 저장.
            context: 감시 범위·자원 소유·최신 취소를 대조한다.
        """
        self.tasks = tasks
        self.context = context

    @transactional
    @override
    async def run(self, command: RecordMonitorNoticeCommand) -> TaskMonitor:
        """같은 시도의 관찰만 보존하고 알림 실패로 실행자를 호출하지 않는다.

        Args:
            command: 관찰한 제출·실패·실제 전달 결과.

        Returns:
            TaskMonitor: 정확한 사건에 저장한 결과.
        """
        task, monitor, _ = await self.context.load(
            project_id=command.project_id,
            session_id=command.session_id,
            task_id=command.task_id,
            monitor_number=command.monitor_number,
            execution_id=command.execution_id,
            generation=command.generation,
        )
        monitor = monitor.notice_result(
            command.event_number, command.attempt, command.status, command.error
        )
        task.update_monitor(monitor)
        await self.tasks.save(task)
        return monitor

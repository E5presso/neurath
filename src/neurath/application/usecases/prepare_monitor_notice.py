"""현재 원장·실행·자원 세대가 일치해야 하는 감시 작업이다."""

from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.repositories.task import ITaskRepository
from neurath.application.ports.services.monitor_context import IMonitorContextService
from neurath.domain.values.task_monitor import TaskMonitor


@immutable
class PrepareMonitorNoticeCommand(AbstractCommand):
    """현재 원장·실행·자원 세대가 일치해야 하는 감시 작업이다.

    Attributes:
        project_id: 태스크의 프로젝트.
        session_id: 현재 소유 세션.
        task_id: 외부 의존을 소유한 태스크.
        monitor_number: 정확한 감시 순번.
        execution_id: 현재 자원 소유 실행.
        generation: 조회 시 확인한 자원 세대.
        event_number: 조회한 정확한 변화 사건의 순번.
    """

    project_id: UUID
    session_id: UUID
    task_id: UUID
    monitor_number: int
    execution_id: UUID
    generation: int
    event_number: int


@UseCase()
class PrepareMonitorNoticeUseCase(
    IAsyncCommandUseCase[PrepareMonitorNoticeCommand, TaskMonitor | None]
):
    """사건 알림의 유한 제출 예산을 외부 전달 전에 커밋한다."""

    def __init__(self, tasks: ITaskRepository, context: IMonitorContextService) -> None:
        """태스크 저장소와 감시 범위 대조 서비스를 주입받는다.

        Args:
            tasks: 알림 시도·미확인 상태 저장.
            context: 감시 범위·자원 소유·최신 취소를 대조한다.
        """
        self.tasks = tasks
        self.context = context

    @transactional
    @override
    async def run(self, command: PrepareMonitorNoticeCommand) -> TaskMonitor | None:
        """현재 사건을 최대 세 번 제출하며 결과 불명을 자동 재전송하지 않는다.

        Args:
            command: 정확한 사건과 현재 자원 소유.

        Returns:
            TaskMonitor | None: 새 제출 예약 또는 추가 제출이 없는 경우 None.
        """
        task, monitor, runnable = await self.context.load(
            project_id=command.project_id,
            session_id=command.session_id,
            task_id=command.task_id,
            monitor_number=command.monitor_number,
            execution_id=command.execution_id,
            generation=command.generation,
        )
        updated = monitor.begin_notice(command.event_number) if runnable else monitor
        task.update_monitor(updated)
        await self.tasks.save(task)
        return (
            updated
            if updated.event(command.event_number).attempts
            > monitor.event(command.event_number).attempts
            else None
        )

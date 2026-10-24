"""현재 원장·실행·자원 세대가 일치해야 하는 감시 작업이다."""

from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.repositories.request_source import IRequestSourceRepository
from neurath.application.ports.repositories.task import ITaskRepository
from neurath.application.ports.services.monitor_context import IMonitorContextService
from neurath.domain.aggregates.request_source import RequestSource, SourceKind
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
        transition_event_id: 실제 전환 큐 사건이며 일반 콜백은 None.
    """

    project_id: UUID
    session_id: UUID
    task_id: UUID
    monitor_number: int
    execution_id: UUID
    generation: int
    transition_event_id: UUID | None = None


@UseCase()
class PrepareMonitorPollUseCase(
    IAsyncCommandUseCase[PrepareMonitorPollCommand, TaskMonitor | None]
):
    """관찰의 중복 실행을 막는 자원과 예산을 먼저 커밋한다."""

    def __init__(
        self,
        tasks: ITaskRepository,
        context: IMonitorContextService,
        sources: IRequestSourceRepository,
    ) -> None:
        """태스크 저장소와 감시 범위 대조 서비스를 주입받는다.

        Args:
            tasks: 감시 예약과 잔여 예산 저장.
            context: 감시 범위·자원 소유·최신 취소를 대조한다.
            sources: 전환 사건의 기술 요약을 기존 기록에 보존한다.
        """
        self.tasks = tasks
        self.context = context
        self.sources = sources

    @transactional
    @override
    async def run(self, command: PrepareMonitorPollCommand) -> TaskMonitor | None:
        """현재 자원만 한 번 예약하며 중복·취소·예산 소진에는 외부 작업을 만들지 않는다.

        Args:
            command: 현재 원장과 자원 소유 세대.

        Returns:
            TaskMonitor | None: 새 예약 또는 새 실행이 없는 경우 None.
        """
        if command.transition_event_id is not None and any(
            source.reference == f"migration-monitor:{command.transition_event_id}"
            for source in await self.sources.find_by_session_id(command.session_id)
        ):
            return None
        task, monitor, runnable = await self.context.load(
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
        if command.transition_event_id is not None and updated.poll_id is None:
            await self.sources.save(
                RequestSource.create(
                    command.project_id,
                    command.session_id,
                    SourceKind.SUMMARY,
                    "Transition monitor callback handled without a new observation; current cancellation and remaining budget retained, no success or delivery inferred.",
                    "migration monitor receipt",
                    f"migration-monitor:{command.transition_event_id}",
                )
            )
        return updated if monitor.poll_id is None and updated.poll_id is not None else None

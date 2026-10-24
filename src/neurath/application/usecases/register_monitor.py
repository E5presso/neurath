"""현재 태스크의 실제 외부 대기에 요청한 감시만 명시적으로 등록한다."""

from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.repositories.execution import IExecutionRepository
from neurath.application.ports.repositories.task import ITaskRepository
from neurath.domain.enums.execution_status import ExecutionStatus
from neurath.domain.errors import ContextNotFound, InvalidTaskState
from neurath.domain.values.task_monitor import MonitorKind, TaskMonitor


@immutable
class RegisterMonitorCommand(AbstractCommand):
    """기존 요청 안의 정확한 외부 대기·대상·예산을 지정한다.

    Attributes:
        project_id: 현재 태스크의 프로젝트.
        session_id: 현재 태스크의 소유 세션.
        task_id: 실제 요청이 보존된 태스크.
        expected_revision: 등록 전에 읽은 원장 개정.
        execution_id: 관찰 자원을 소유할 실제 실행.
        kind: 지원하는 결정론적 관찰 종류.
        target: 기존 대기와 정확히 같은 외부 대상.
        budget: 허용한 유한 관찰 횟수.
    """

    project_id: UUID
    session_id: UUID
    task_id: UUID
    expected_revision: int
    execution_id: UUID
    kind: MonitorKind
    target: str
    budget: int


@UseCase()
class RegisterMonitorUseCase(IAsyncCommandUseCase[RegisterMonitorCommand, TaskMonitor]):
    """대기 이유만으로 실행하지 않고 명시한 감시 요청을 보존한다."""

    def __init__(self, tasks: ITaskRepository, executions: IExecutionRepository) -> None:
        """원장과 실제 소유 실행을 확인할 저장소를 받는다.

        Args:
            tasks: 외부 대기와 감시 이력을 함께 저장한다.
            executions: 같은 세션의 실제 실행을 확인한다.
        """
        self.tasks = tasks
        self.executions = executions

    @transactional
    @override
    async def run(self, command: RegisterMonitorCommand) -> TaskMonitor:
        """범위·개정·실제 실행·중복을 확인하고 감시를 원장에 저장한다.

        Args:
            command: 원래 요청의 정확한 외부 의존 감시.

        Returns:
            TaskMonitor: 아직 첫 관찰을 수행하지 않은 감시.

        Raises:
            ContextNotFound: 소유 세션과 실제 실행이 다른 경우.
            InvalidTaskState: 실제 실행이 취소·종료된 경우.
        """
        task = await self.tasks.get(command.task_id)
        task.require_scope(command.project_id, command.session_id)
        task.require_revision(command.expected_revision)
        execution = await self.executions.get(command.execution_id)
        if execution.session_id != command.session_id:
            raise ContextNotFound("Monitor execution belongs to another session")
        if execution.status not in (ExecutionStatus.RUNNING, ExecutionStatus.PAUSED):
            raise InvalidTaskState("Cannot register monitoring for a stopped execution")
        monitor = task.register_monitor(
            command.execution_id, command.kind, command.target, command.budget
        )
        await self.tasks.save(task)
        return monitor

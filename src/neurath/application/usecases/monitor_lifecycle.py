"""태스크 감시의 예약·관찰·소비·취소·복구를 현재 원장에 대조한다."""

from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.repositories.execution import IExecutionRepository
from neurath.application.ports.repositories.task import ITaskRepository
from neurath.domain.aggregates.task import Task
from neurath.domain.errors import ContextNotFound
from neurath.domain.monitoring import NoticeStatus, TaskMonitor
from neurath.domain.runtime_records import ExecutionStatus, Liveness


@immutable
class MonitorCommand(AbstractCommand):
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


@immutable
class RecordMonitorObservationCommand(MonitorCommand):
    """실제 완료한 정확한 관찰 자원의 결과다.

    Attributes:
        poll_id: 관찰 전에 저장한 자원 ID.
        state: 완결된 외부 상태이며 출력 조각이면 None.
        reference: 실제 관찰 근거.
        error: 관찰 실패와 필요한 조작.
    """

    poll_id: UUID
    state: str | None
    reference: str
    error: str = ""


@immutable
class MonitorEventCommand(MonitorCommand):
    """정확한 변화 사건을 선택한다.

    Attributes:
        event_number: 감시 안의 사건 순번.
    """

    event_number: int


@immutable
class ResolveMonitorEventCommand(MonitorEventCommand):
    """기존 해소 조건을 확인한 근거로 명시적으로 대기를 재개한다.

    Attributes:
        resolution: 원 조건을 충족했다는 실제 관찰 근거.
    """

    resolution: str


@immutable
class RecoverMonitorCommand(MonitorCommand):
    """중단한 자원을 실제 관찰한 경우에만 예약을 해제한다.

    Attributes:
        poll_id: 실제 종료를 관찰한 정확한 자원.
        liveness: 관찰한 자원의 생존 상태.
    """

    poll_id: UUID
    liveness: Liveness


@immutable
class RecordMonitorNoticeCommand(MonitorEventCommand):
    """같은 알림 제출에 대한 결과만 지정한다.

    Attributes:
        attempt: 결과를 관찰한 제출 시도.
        status: 제출·실패 또는 실제 전달 확인.
        error: 실패 사유와 필요한 조작.
    """

    attempt: int
    status: NoticeStatus
    error: str = ""


async def load_monitor(
    tasks: ITaskRepository, executions: IExecutionRepository, command: MonitorCommand
) -> tuple[Task, TaskMonitor, bool]:
    """범위·자원 소유·현재 취소를 확인하고 원장 안의 감시를 대조한다.

    Args:
        tasks: 현재 요구와 대기를 조회한다.
        executions: 실제 소유 실행을 조회한다.
        command: 정확한 범위와 자원 세대.

    Returns:
        tuple[Task, TaskMonitor, bool]: 최신 원장·감시와 종료되지 않은 실행 여부.

    Raises:
        ContextNotFound: 실제 실행과 원장 소유 세션이 다른 경우.
    """
    task = await tasks.get(command.task_id)
    task.require_scope(command.project_id, command.session_id)
    task.monitor(command.monitor_number).require_owner(command.execution_id, command.generation)
    execution = await executions.get(command.execution_id)
    if execution.session_id != command.session_id:
        raise ContextNotFound("Monitor execution belongs to another session")
    monitor = task.reconcile_monitor(
        command.monitor_number, cancelled=execution.status is ExecutionStatus.CANCELLED
    )
    return task, monitor, execution.status in (ExecutionStatus.RUNNING, ExecutionStatus.PAUSED)


@UseCase()
class PrepareMonitorPollUseCase(IAsyncCommandUseCase[MonitorCommand, TaskMonitor | None]):
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
    async def run(self, command: MonitorCommand) -> TaskMonitor | None:
        """현재 자원만 한 번 예약하며 중복·취소·예산 소진에는 외부 작업을 만들지 않는다.

        Args:
            command: 현재 원장과 자원 소유 세대.

        Returns:
            TaskMonitor | None: 새 예약 또는 새 실행이 없는 경우 None.
        """
        task, monitor, runnable = await load_monitor(self.tasks, self.executions, command)
        updated = monitor.begin_poll() if runnable else monitor
        task.update_monitor(updated)
        await self.tasks.save(task)
        return updated if monitor.poll_id is None and updated.poll_id is not None else None


@UseCase()
class RecordMonitorObservationUseCase(
    IAsyncCommandUseCase[RecordMonitorObservationCommand, TaskMonitor]
):
    """외부 관찰 후 최신 취소·요구 개정을 대조하여 사건만 저장한다."""

    def __init__(self, tasks: ITaskRepository, executions: IExecutionRepository) -> None:
        """원장과 실제 실행 저장소를 받는다.

        Args:
            tasks: 관찰과 변화 사건 저장.
            executions: 관찰 중 발생한 취소 확인.
        """
        self.tasks = tasks
        self.executions = executions

    @transactional
    @override
    async def run(self, command: RecordMonitorObservationCommand) -> TaskMonitor:
        """관찰 결과를 저장하며 첫 관찰·동일 상태는 새 사건으로 승격하지 않는다.

        Args:
            command: 실제 자원의 완결 상태·관찰·실패.

        Returns:
            TaskMonitor: 정확한 사건을 포함한 최신 감시.
        """
        task, monitor, _ = await load_monitor(self.tasks, self.executions, command)
        wait = task.waits[monitor.wait_number - 1]
        monitor = monitor.observe(
            command.poll_id,
            command.state,
            command.reference,
            command.error,
            f"""External dependency changed: {wait.target}
Condition: {wait.condition}
Authorized follow-up: {wait.resume_scope}
Read the exact event before ACK. ACK is not dependency resolution or task success.""",
        )
        task.update_monitor(monitor)
        await self.tasks.save(task)
        return monitor


@UseCase()
class AcknowledgeMonitorEventUseCase(IAsyncCommandUseCase[MonitorEventCommand, TaskMonitor]):
    """사건 하나의 ACK만 보존하며 작업·대기 해소 권한과 구분한다."""

    def __init__(self, tasks: ITaskRepository, executions: IExecutionRepository) -> None:
        """정확한 사건을 저장할 의존성을 받는다.

        Args:
            tasks: 원 사건 소비 저장.
            executions: 현재 소유·취소 대조.
        """
        self.tasks = tasks
        self.executions = executions

    @transactional
    @override
    async def run(self, command: MonitorEventCommand) -> TaskMonitor:
        """지정 사건만 소비하고 원 조건·예산·알림은 유지한다.

        Args:
            command: 조회한 정확한 사건과 소유 세대.

        Returns:
            TaskMonitor: ACK가 기록된 최신 감시.
        """
        task, monitor, _ = await load_monitor(self.tasks, self.executions, command)
        monitor = monitor.acknowledge(command.event_number)
        task.update_monitor(monitor)
        await self.tasks.save(task)
        return monitor


@UseCase()
class ResolveMonitorEventUseCase(IAsyncCommandUseCase[ResolveMonitorEventCommand, TaskMonitor]):
    """원 해소 조건의 명시적 판단만 현재 시도의 재개로 연결한다."""

    def __init__(self, tasks: ITaskRepository, executions: IExecutionRepository) -> None:
        """원 대기와 실행을 대조할 의존성을 받는다.

        Args:
            tasks: 대기 해소와 사건 소비의 원자적 저장.
            executions: 현재 소유·취소 대조.
        """
        self.tasks = tasks
        self.executions = executions

    @transactional
    @override
    async def run(self, command: ResolveMonitorEventCommand) -> TaskMonitor:
        """정확한 사건과 해소 근거를 보존하고 현재 작업을 active로 돌린다.

        Args:
            command: 실제 해소 판단에 사용한 사건과 근거.

        Returns:
            TaskMonitor: 해소 사건과 감시 종료를 보존한 값.
        """
        task, _, _ = await load_monitor(self.tasks, self.executions, command)
        task.resolve_monitor(command.monitor_number, command.event_number, command.resolution)
        await self.tasks.save(task)
        return task.monitor(command.monitor_number)


@UseCase()
class CancelMonitorUseCase(IAsyncCommandUseCase[MonitorCommand, TaskMonitor]):
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
    async def run(self, command: MonitorCommand) -> TaskMonitor:
        """감시만 중지하고 태스크·원 대기·미확인 자원은 보존한다.

        Args:
            command: 취소할 정확한 감시.

        Returns:
            TaskMonitor: 취소와 미확인 자원을 포함한 감시.
        """
        task, monitor, _ = await load_monitor(self.tasks, self.executions, command)
        monitor = monitor.cancel("Monitoring explicitly cancelled")
        task.update_monitor(monitor)
        await self.tasks.save(task)
        return monitor


@UseCase()
class RecoverMonitorUseCase(IAsyncCommandUseCase[RecoverMonitorCommand, TaskMonitor]):
    """실제 자원 종료를 현재 소유 세대와 비교하여 복구한다."""

    def __init__(self, tasks: ITaskRepository, executions: IExecutionRepository) -> None:
        """최신 취소·자원 상태를 대조할 의존성을 받는다.

        Args:
            tasks: 자원 종료·새 세대·남은 예산 저장.
            executions: 현재 소유 실행 대조.
        """
        self.tasks = tasks
        self.executions = executions

    @transactional
    @override
    async def run(self, command: RecoverMonitorCommand) -> TaskMonitor:
        """종료한 자원만 해제하며 취소를 해제하거나 잔여 예산을 늘리지 않는다.

        Args:
            command: 정확한 자원과 실제 종료 관찰.

        Returns:
            TaskMonitor: 현재 취소와 새 세대를 보존한 감시.
        """
        task, monitor, _ = await load_monitor(self.tasks, self.executions, command)
        monitor = monitor.recover(command.poll_id, command.liveness)
        task.update_monitor(monitor)
        await self.tasks.save(task)
        return monitor


@UseCase()
class PrepareMonitorNoticeUseCase(IAsyncCommandUseCase[MonitorEventCommand, TaskMonitor | None]):
    """사건 알림의 유한 제출 예산을 외부 전달 전에 커밋한다."""

    def __init__(self, tasks: ITaskRepository, executions: IExecutionRepository) -> None:
        """현재 원장·실행을 확인할 저장소를 받는다.

        Args:
            tasks: 알림 시도·미확인 상태 저장.
            executions: 취소·종료 대조.
        """
        self.tasks = tasks
        self.executions = executions

    @transactional
    @override
    async def run(self, command: MonitorEventCommand) -> TaskMonitor | None:
        """현재 사건을 최대 세 번 제출하며 결과 불명을 자동 재전송하지 않는다.

        Args:
            command: 정확한 사건과 현재 자원 소유.

        Returns:
            TaskMonitor | None: 새 제출 예약 또는 추가 제출이 없는 경우 None.
        """
        task, monitor, runnable = await load_monitor(self.tasks, self.executions, command)
        updated = monitor.begin_notice(command.event_number) if runnable else monitor
        task.update_monitor(updated)
        await self.tasks.save(task)
        return (
            updated
            if updated.event(command.event_number).attempts
            > monitor.event(command.event_number).attempts
            else None
        )


@UseCase()
class RecordMonitorNoticeUseCase(IAsyncCommandUseCase[RecordMonitorNoticeCommand, TaskMonitor]):
    """외부 제출 결과와 확인 가능한 실제 전달을 원 사건에 저장한다."""

    def __init__(self, tasks: ITaskRepository, executions: IExecutionRepository) -> None:
        """정확한 시도·취소를 확인할 저장소를 받는다.

        Args:
            tasks: 원 사건과 제출 실패 저장.
            executions: 제출 중 취소 대조.
        """
        self.tasks = tasks
        self.executions = executions

    @transactional
    @override
    async def run(self, command: RecordMonitorNoticeCommand) -> TaskMonitor:
        """같은 시도의 관찰만 보존하고 알림 실패로 실행자를 호출하지 않는다.

        Args:
            command: 관찰한 제출·실패·실제 전달 결과.

        Returns:
            TaskMonitor: 정확한 사건에 저장한 결과.
        """
        task, monitor, _ = await load_monitor(self.tasks, self.executions, command)
        monitor = monitor.notice_result(
            command.event_number, command.attempt, command.status, command.error
        )
        task.update_monitor(monitor)
        await self.tasks.save(task)
        return monitor

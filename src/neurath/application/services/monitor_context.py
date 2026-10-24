"""범위·자원 소유·현재 취소를 확인하고 원장 안의 감시를 대조한다."""

from uuid import UUID

from neurath.application.ports.repositories.execution import IExecutionRepository
from neurath.application.ports.repositories.task import ITaskRepository
from neurath.domain.aggregates.task import Task
from neurath.domain.enums.execution_status import ExecutionStatus
from neurath.domain.errors import ContextNotFound
from neurath.domain.values.task_monitor import TaskMonitor


async def load_monitor(
    tasks: ITaskRepository,
    executions: IExecutionRepository,
    *,
    project_id: UUID,
    session_id: UUID,
    task_id: UUID,
    monitor_number: int,
    execution_id: UUID,
    generation: int,
) -> tuple[Task, TaskMonitor, bool]:
    """범위·자원 소유·현재 취소를 확인하고 원장 안의 감시를 대조한다.

    Args:
        tasks: 현재 요구와 대기를 조회한다.
        executions: 실제 소유 실행을 조회한다.
        project_id: 태스크의 프로젝트.
        session_id: 현재 소유 세션.
        task_id: 조회할 태스크.
        monitor_number: 감시 순번.
        execution_id: 소유 실행.
        generation: 조회 시 확인한 자원 세대.

    Returns:
        tuple[Task, TaskMonitor, bool]: 최신 원장·감시와 종료되지 않은 실행 여부.

    Raises:
        ContextNotFound: 실제 실행과 원장 소유 세션이 다른 경우.
    """
    task = await tasks.get(task_id)
    task.require_scope(project_id, session_id)
    task.monitor(monitor_number).require_owner(execution_id, generation)
    execution = await executions.get(execution_id)
    if execution.session_id != session_id:
        raise ContextNotFound("Monitor execution belongs to another session")
    monitor = task.reconcile_monitor(
        monitor_number, cancelled=execution.status is ExecutionStatus.CANCELLED
    )
    return task, monitor, execution.status in (ExecutionStatus.RUNNING, ExecutionStatus.PAUSED)

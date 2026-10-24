"""기존 SQLAlchemy 저장소로 감시 작업의 현재 원장과 실행을 조회한다."""

from typing import override
from uuid import UUID

from spakky.core.pod.annotations.pod import Pod

from neurath.application.ports.services.monitor_context import IMonitorContextService
from neurath.domain.aggregates.task import Task
from neurath.domain.values.task_monitor import TaskMonitor
from neurath.infrastructure.repositories.execution import SQLAlchemyExecutionRepository
from neurath.infrastructure.repositories.task import SQLAlchemyTaskRepository


@Pod()
class SQLAlchemyMonitorContextService(IMonitorContextService):
    """SQLAlchemy 저장소의 기본 조회를 재사용하고 정책 판단은 도메인에 위임한다."""

    def __init__(
        self, tasks: SQLAlchemyTaskRepository, executions: SQLAlchemyExecutionRepository
    ) -> None:
        """같은 요청 세션을 사용하는 SQLAlchemy 저장소를 주입받는다.

        Args:
            tasks: 현재 태스크·감시를 조회할 저장소.
            executions: 현재 소유 실행을 조회할 저장소.
        """
        self.tasks = tasks
        self.executions = executions

    @override
    async def load(
        self,
        *,
        project_id: UUID,
        session_id: UUID,
        task_id: UUID,
        monitor_number: int,
        execution_id: UUID,
        generation: int,
    ) -> tuple[Task, TaskMonitor, bool]:
        """범위·자원 소유를 검증하고 최신 취소를 반영한 저장 전 상태를 반환한다.

        Args:
            project_id: 요청한 프로젝트.
            session_id: 현재 소유 세션.
            task_id: 외부 대기를 소유한 태스크.
            monitor_number: 대조할 감시 순번.
            execution_id: 감시 자원의 소유 실행.
            generation: 조회 시 확인한 자원 세대.

        Returns:
            tuple[Task, TaskMonitor, bool]: 현재 태스크·대조한 감시와 새 관찰·알림 허용 여부.
        """
        task = await self.tasks.get(task_id)
        task.require_scope(project_id, session_id)
        task.monitor(monitor_number).require_owner(execution_id, generation)
        execution = await self.executions.get(execution_id)
        execution.require_session(session_id)
        monitor = task.reconcile_monitor(monitor_number, cancelled=execution.is_cancelled)
        return task, monitor, execution.allows_monitoring

"""최종 결과 보고 전에 작업과 선택 절차를 짧은 읽기 요청으로 관찰한다."""

from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.query import AbstractQuery, IAsyncQueryUseCase

from neurath.application.ports.repositories.task import ITaskRepository
from neurath.application.ports.repositories.workflow import IWorkflowRepository
from neurath.domain.aggregates.task import Task
from neurath.domain.aggregates.workflow import WorkflowRun


@immutable
class ReadResultContextQuery(AbstractQuery):
    """결과를 보고할 작업 범위를 지정한다.

    Attributes:
        project_id: 원래 프로젝트.
        session_id: 작업 소유 세션.
        task_id: 실제 결과를 보고할 작업.
    """

    project_id: UUID
    session_id: UUID
    task_id: UUID


@immutable
class ReadResultContext:
    """외부 관찰 전에 확인한 원장 스냅샷이다.

    Attributes:
        task: 현재 작업과 요구 개정.
        workflow: 연결된 선택 절차 또는 None.
    """

    task: Task
    workflow: WorkflowRun | None


@UseCase()
class ReadResultContextUseCase(IAsyncQueryUseCase[ReadResultContextQuery, ReadResultContext]):
    """외부 파일을 읽지 않고 현재 작업과 절차만 조회한다."""

    def __init__(self, tasks: ITaskRepository, workflows: IWorkflowRepository) -> None:
        """작업과 절차의 저장 계약을 받는다.

        Args:
            tasks: 현재 작업 조회.
            workflows: 연결된 절차 조회.
        """
        self.tasks = tasks
        self.workflows = workflows

    @transactional
    @override
    async def run(self, query: ReadResultContextQuery) -> ReadResultContext:
        """원래 범위를 확인한 원장 스냅샷을 반환한다.

        Args:
            query: 조회할 작업 범위.

        Returns:
            ReadResultContext: DB 요청 수명 밖에서도 읽을 수 있는 상태.
        """
        task = await self.tasks.get(query.task_id)
        task.require_scope(query.project_id, query.session_id)
        return ReadResultContext(task=task, workflow=await self.workflows.find_by_task_id(task.uid))

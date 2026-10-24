"""실행 전에 평가 후보와 기존 협업 배정을 같은 phase 시도로 연결한다."""

from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.repositories.delegation import IDelegationRepository
from neurath.application.ports.repositories.task import ITaskRepository
from neurath.application.ports.repositories.workflow import IWorkflowRepository
from neurath.application.ports.services.evaluation_context import IEvaluationContextService
from neurath.domain.aggregates.workflow import WorkflowRun
from neurath.domain.enums.task_status import TaskStatus
from neurath.domain.values.external_wait import ExternalWait


@immutable
class BindEvaluationCommand(AbstractCommand):
    """평가할 현재 실행과 저장된 배정을 지정한다.

    Attributes:
        project_id: 요청 프로젝트.
        session_id: 실행 소유 세션.
        run_id: 기존 스킬 실행.
        phase_key: 평가 단계 이름.
        delegation_id: 준비한 실제 검토 배정.
    """

    project_id: UUID
    session_id: UUID
    run_id: UUID
    phase_key: str
    delegation_id: UUID


@UseCase()
class BindEvaluationUseCase(IAsyncCommandUseCase[BindEvaluationCommand, WorkflowRun]):
    """현재 후보를 다시 확인해 변경 중인 결과에 옛 평가를 연결하지 않는다."""

    def __init__(
        self,
        workflows: IWorkflowRepository,
        tasks: ITaskRepository,
        delegations: IDelegationRepository,
        context: IEvaluationContextService,
    ) -> None:
        """현재 작업과 배정의 저장 경계를 받는다.

        Args:
            workflows: 단계 시도를 저장한다.
            tasks: 현재 요구를 확인한다.
            delegations: 저장된 검토 배정을 읽는다.
            context: 현재 후보를 다시 계산한다.
        """
        self.workflows = workflows
        self.tasks = tasks
        self.delegations = delegations
        self.context = context

    @transactional
    @override
    async def run(self, command: BindEvaluationCommand) -> WorkflowRun:
        """같은 후보의 기존 시도를 재사용하고 최초 배정만 예약한다.

        Args:
            command: 실행·단계와 배정 연결.

        Returns:
            WorkflowRun: 실제 외부 호출 전에 커밋할 단계 연결.
        """
        run = await self.workflows.get(command.run_id)
        run.require_scope(command.project_id, command.session_id)
        phase = run.evaluation_phase(command.phase_key)
        delegation = await self.delegations.get(command.delegation_id)
        task = await self.tasks.get(run.task_id)
        delegation.require_current(task)
        context = await self.context.load(run, phase)
        existing = run.latest(phase)
        if (
            existing is not None
            and existing.delegation_id == delegation.uid
            and existing.candidate == context.candidate
        ):
            return run
        run.require_task(task, recovering=True)
        if task.status is TaskStatus.WAITING:
            task.resume("Related evaluation candidate changed")
        attempt = run.bind_evaluation(phase, delegation, context.candidate)
        task.wait(
            ExternalWait(
                target=f"{run.uid}:{attempt.number}",
                condition="independent evaluation report received",
                resume_scope=f"consume evaluation {run.uid}:{attempt.number}",
                observation=f"delegation:{delegation.uid}; candidate:{context.candidate}",
            )
        )
        await self.tasks.save(task)
        return await self.workflows.save(run)

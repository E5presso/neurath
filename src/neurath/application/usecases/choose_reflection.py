"""회고 제안과 일반 사용자 선택을 기존 스킬의 선택 분기에 기록한다."""

from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.repositories.delegation import IDelegationRepository
from neurath.application.ports.repositories.task import ITaskRepository
from neurath.application.ports.repositories.workflow import IWorkflowRepository
from neurath.domain.aggregates.workflow import WorkflowRun
from neurath.domain.enums.reflection_choice import ReflectionChoice
from neurath.domain.enums.task_status import TaskStatus
from neurath.domain.values.evaluation_target import EvaluationKind


@immutable
class ChooseReflectionCommand(AbstractCommand):
    """별도 토큰 없이 실제 사용자 발화와 선택을 전달한다.

    Attributes:
        project_id: 요청 프로젝트.
        session_id: 실행 소유 세션.
        run_id: 마무리할 기존 실행.
        choice: 제안·요청·거절·무응답 선택.
        reason: 관찰한 문제 또는 사용자 발화의 근거.
    """

    project_id: UUID
    session_id: UUID
    run_id: UUID
    choice: ReflectionChoice
    reason: str


@UseCase()
class ChooseReflectionUseCase(IAsyncCommandUseCase[ChooseReflectionCommand, WorkflowRun]):
    """미수락 회고가 원 작업 종료를 막지 않게 선택만 보존한다."""

    def __init__(
        self,
        workflows: IWorkflowRepository,
        delegations: IDelegationRepository,
        tasks: ITaskRepository,
    ) -> None:
        """기존 절차의 저장 경계를 받는다.

        Args:
            workflows: 사용자 선택을 소유한 실행 저장소.
            delegations: 취소한 회고의 정확한 수신 배정.
            tasks: 원래 작업의 회고 대기만 해소한다.
        """
        self.workflows = workflows
        self.delegations = delegations
        self.tasks = tasks

    @transactional
    @override
    async def run(self, command: ChooseReflectionCommand) -> WorkflowRun:
        """회고를 요청한 경우에만 선택적 평가 단계를 활성화한다.

        Args:
            command: 일반 발화의 선택과 근거.

        Returns:
            WorkflowRun: 선택을 보존한 기존 실행.
        """
        run = await self.workflows.get(command.run_id)
        run.require_scope(command.project_id, command.session_id)
        if command.choice in (ReflectionChoice.DECLINED, ReflectionChoice.UNANSWERED):
            task = await self.tasks.get(run.task_id)
            for attempt in run.attempts:
                phase = run.phase_for(attempt)
                if (
                    phase.evaluation is None
                    or phase.evaluation.kind is not EvaluationKind.REFLECTION
                ):
                    continue
                if attempt.delegation_id is not None:
                    delegation = await self.delegations.get(attempt.delegation_id)
                    delegation.request_stop(command.reason)
                    await self.delegations.save(delegation)
                if (
                    task.status is TaskStatus.WAITING
                    and task.waits[-1].target == f"{run.uid}:{attempt.number}"
                ):
                    task.resume(command.reason)
                    await self.tasks.save(task)
        run.choose_reflection(command.choice, command.reason)
        return await self.workflows.save(run)

"""독립 보고의 충족·미달 판단을 현재 후보와 대조하여 기존 phase에 반영한다."""

from collections.abc import Sequence
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


@immutable
class ConsumeEvaluationCommand(AbstractCommand):
    """보고를 원문·증거와 대조한 실행자의 판단이다.

    Attributes:
        project_id: 요청 프로젝트.
        session_id: 실행 소유 세션.
        run_id: 기존 실행.
        phase_key: 현재 평가 단계.
        accepted: 실제 요구를 충족했는지 여부.
        rationale: 지적 수용·오판 기각의 구체 근거.
        references: 원문·실제 검증 참조.
    """

    project_id: UUID
    session_id: UUID
    run_id: UUID
    phase_key: str
    accepted: bool
    rationale: str
    references: Sequence[str]


@UseCase()
class ConsumeEvaluationUseCase(IAsyncCommandUseCase[ConsumeEvaluationCommand, WorkflowRun]):
    """평가자가 원 태스크를 성공시키지 않고 담당 실행자가 보고를 대조한다."""

    def __init__(
        self,
        workflows: IWorkflowRepository,
        delegations: IDelegationRepository,
        context: IEvaluationContextService,
        tasks: ITaskRepository,
    ) -> None:
        """원 보고와 현재 후보 조회·저장 계약을 받는다.

        Args:
            workflows: 평가 단계와 결과를 저장한다.
            delegations: 실제 독립 보고를 조회한다.
            context: 현재 관련 요구와 산출물을 대조한다.
            tasks: 해당 평가의 외부 대기만 해소한다.
        """
        self.workflows = workflows
        self.delegations = delegations
        self.context = context
        self.tasks = tasks

    @transactional
    @override
    async def run(self, command: ConsumeEvaluationCommand) -> WorkflowRun:
        """실제 완료 보고와 현재 후보가 같을 때만 판단을 반영한다.

        Args:
            command: 원문·근거에 기반한 실행자의 검토 판단.

        Returns:
            WorkflowRun: 성공 또는 미달을 보존한 동일 실행.

        Raises:
            ValueError: 아직 실제 평가 배정을 연결하지 않은 경우.
        """
        run = await self.workflows.get(command.run_id)
        run.require_scope(command.project_id, command.session_id)
        phase = run.evaluation_phase(command.phase_key)
        attempt = run.latest(phase)
        if attempt is None or attempt.delegation_id is None:
            raise ValueError("Evaluation has not been assigned")
        context = await self.context.load(run, phase)
        run.consume_evaluation(
            attempt.number,
            await self.delegations.get(attempt.delegation_id),
            context.candidate,
            accepted=command.accepted,
            rationale=command.rationale,
            references=command.references,
        )
        task = await self.tasks.get(run.task_id)
        if (
            task.status is TaskStatus.WAITING
            and task.waits[-1].target == f"{run.uid}:{attempt.number}"
        ):
            task.resume(command.rationale)
            await self.tasks.save(task)
        return await self.workflows.save(run)

"""시도에 관찰 결과를 반영하고 충족한 단계만 다음 순서로 진행시킨다."""

from dataclasses import dataclass
from typing import override

from spakky.core.pod.annotations.pod import Pod
from spakky.core.stereotype.usecase import UseCase
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.repositories.task import ITaskRepository
from neurath.application.ports.repositories.workflow import IWorkflowRepository
from neurath.domain.aggregates.workflow import WorkflowRun
from neurath.domain.task_records import ExternalWait, TaskStatus
from neurath.domain.workflow_records import PhaseResult, PhaseStatus


@dataclass(frozen=True)
class ReportPhaseCommand(AbstractCommand):
    """관찰한 단계 결과를 동일한 run·시도에 연결하는 요청이다.

    Attributes:
        project_id: run이 속하는 프로젝트 ID.
        session_id: run을 소유한 세션 ID.
        run_id: 결과를 기록할 run ID.
        attempt_number: 관찰 대상인 보존된 시도 번호.
        result: 대상 개정·검사·근거가 포함된 관찰 결과.
    """

    project_id: str
    session_id: str
    run_id: str
    attempt_number: int
    result: PhaseResult


@dataclass(frozen=True)
class ReportPhaseResult:
    """결과가 저장된 run. 옛 정의의 결과는 보존하되 현재 단계에 자동 적용하지 않는다.

    Attributes:
        run: 결과가 저장된 run. 옛 정의의 결과는 보존하되 현재 단계에 자동 적용하지 않는다.
    """

    run: WorkflowRun


@UseCase(scope=Pod.Scope.CONTEXT)
class ReportPhaseUseCase(IAsyncCommandUseCase[ReportPhaseCommand, ReportPhaseResult]):
    """시도에 관찰 결과를 반영하고 충족한 단계만 다음 순서로 진행시킨다.

    현재 단계에 적용되는 결과 불명은 연결 태스크도 외부 대기로 전환한다.
    같은 시도의 결과가 확인되면 그 대기만 해소한다. 옛 정의의 결과나
    다른 의존의 대기를 통해 현재 요구를 완료하거나 재개하지 않는다.
    """

    def __init__(self, workflows: IWorkflowRepository, tasks: ITaskRepository) -> None:
        """태스크와 연결된 절차의 조회·저장 포트를 받는다.

        Args:
            workflows: run의 정의·시도를 조회하고 변경 전체를 저장한다.
            tasks: 현재 단계의 외부 대기·해소를 연결 태스크에 반영한다.
        """
        self.workflows = workflows
        self.tasks = tasks

    @override
    async def run(self, command: ReportPhaseCommand) -> ReportPhaseResult:
        """시도에 관찰 결과를 반영하고 충족한 단계만 다음 순서로 진행시킨다.

        Args:
            command: run·시도 ID와 실제 대상 개정·검사·근거를 가진 결과.

        Returns:
            ReportPhaseResult: 결과가 저장된 run. 옛 정의의 결과는 보존하되 현재 단계에 자동 적용하지 않는다.
        """
        run = await self.workflows.get(command.run_id)
        run.require_scope(command.project_id, command.session_id)
        run.report(command.attempt_number, command.result)
        task = await self.tasks.get(run.task_id)
        if (
            not run.applies_to_current(command.attempt_number)
            or task.definition.number != run.revisions[-1].task_definition_number
        ):
            return ReportPhaseResult(run=(await self.workflows.save(run)))
        request_id = f"{run.uid}:{command.attempt_number}"
        if command.result.status is PhaseStatus.WAITING and task.status is TaskStatus.ACTIVE:
            task.wait(
                ExternalWait(
                    target=request_id,
                    condition="execution result observed",
                    resume_scope=f"continue workflow {run.uid}",
                    observation=command.result.summary,
                )
            )
        elif (
            command.result.status is not PhaseStatus.WAITING
            and task.status is TaskStatus.WAITING
            and task.waits[-1].target == request_id
        ):
            task.resume(command.result.summary)
        (await self.tasks.save(task))
        return ReportPhaseResult(run=(await self.workflows.save(run)))

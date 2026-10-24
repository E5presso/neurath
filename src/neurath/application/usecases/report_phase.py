"""시도에 관찰 결과를 반영하고 충족한 단계만 다음 순서로 진행시킨다."""

from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.repositories.task import ITaskRepository
from neurath.application.ports.repositories.workflow import IWorkflowRepository
from neurath.domain.aggregates.workflow import WorkflowRun
from neurath.domain.enums.task_status import TaskStatus
from neurath.domain.errors import InvalidWorkflowState
from neurath.domain.values.external_wait import ExternalWait
from neurath.domain.values.phase_attempt import PhaseResult, PhaseStatus


@immutable
class ReportPhaseCommand(AbstractCommand):
    """관찰한 단계 결과를 동일한 run·시도에 연결하는 요청이다.

    Attributes:
        project_id: run이 속하는 프로젝트 ID.
        session_id: run을 소유한 세션 ID.
        run_id: 결과를 기록할 run ID.
        attempt_number: 관찰 대상인 보존된 시도 번호.
        result: 대상 개정·검사·근거가 포함된 관찰 결과.
        notify_waiting: 외부 실행 결과가 새 대기 상태이면 커밋 뒤 안내한다.
    """

    project_id: UUID
    session_id: UUID
    run_id: UUID
    attempt_number: int | None
    result: PhaseResult
    notify_waiting: bool = False


@immutable
class ReportPhaseResult:
    """결과가 저장된 run. 옛 정의의 결과는 보존하되 현재 단계에 자동 적용하지 않는다.

    Attributes:
        run: 결과가 저장된 run. 옛 정의의 결과는 보존하되 현재 단계에 자동 적용하지 않는다.
    """

    run: WorkflowRun


@UseCase()
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

    @transactional
    @override
    async def run(self, command: ReportPhaseCommand) -> ReportPhaseResult:
        """시도에 관찰 결과를 반영하고 충족한 단계만 다음 순서로 진행시킨다.

        Args:
            command: run·시도 ID와 실제 대상 개정·검사·근거를 가진 결과.

        Raises:
            InvalidWorkflowState: 보고할 현재 단계가 없는 경우.

        Returns:
            ReportPhaseResult: 결과가 저장된 run. 옛 정의의 결과는 보존하되 현재 단계에 자동 적용하지 않는다.
        """
        run = await self.workflows.get(command.run_id)
        run.require_scope(command.project_id, command.session_id)
        number = command.attempt_number
        if number is None:
            phase = run.current
            if phase is None:
                raise InvalidWorkflowState("Workflow is already complete")
            previous = run.latest(phase)
            if previous is None or previous.status is PhaseStatus.FAILED:
                number = run.begin().number
            else:
                number = previous.number
        run.report(number, command.result, notify_waiting=command.notify_waiting)
        task = await self.tasks.get(run.task_id)
        if (
            not run.applies_to_current(number)
            or task.definition.number != run.revisions[-1].task_definition_number
        ):
            return ReportPhaseResult(run=(await self.workflows.save(run)))
        request_id = f"{run.uid}:{number}"
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

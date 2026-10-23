"""워크플로우의 실행 시도를 예약하고 커밋 후 처리할 이벤트를 기록한다."""

from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.repositories.task import ITaskRepository
from neurath.application.ports.repositories.workflow import IWorkflowRepository
from neurath.domain.aggregates.workflow import WorkflowRun
from neurath.domain.workflow_records import PhaseStatus


@immutable
class ExecutePhaseCommand(AbstractCommand):
    """실행하거나 기존 미확정 시도를 조정할 run을 지정한다.

    Attributes:
        project_id: run의 프로젝트 ID.
        session_id: 실행 소유 세션 ID.
        run_id: 처리할 run ID.
        expected_revision: 새 시도를 시작할 때 대조할 run 저장 버전.
    """

    project_id: UUID
    session_id: UUID
    run_id: UUID
    expected_revision: int


@immutable
class ExecutePhaseResult:
    """실행 요청이 커밋될 때의 워크플로우와 시도 식별자를 반환한다.

    Attributes:
        run: 예약 시점 스냅샷이며 후속 실행의 완료를 뜻하지 않는다.
        request_id: 외부 실행·관찰에 사용한 시도 ID. 이미 완료됐으면 None.
    """

    run: WorkflowRun
    request_id: str | None


@UseCase()
class ExecutePhaseUseCase(IAsyncCommandUseCase[ExecutePhaseCommand, ExecutePhaseResult]):
    """실행 요청을 예약하고 커밋 후 이벤트 핸들러가 실행·결과 저장을 이어가게 한다.

    반환값은 예약 시점의 스냅샷이며 실행 완료 판정은 현재 워크플로우 조회로 확인한다.
    """

    def __init__(self, workflows: IWorkflowRepository, tasks: ITaskRepository) -> None:
        """실행 요청을 원자적으로 예약할 저장소를 받는다.

        Args:
            workflows: 단계 정의와 실행 시도를 보존한다.
            tasks: 현재 요구와 실행 가능 상태를 확인한다.
        """
        self.workflows = workflows
        self.tasks = tasks

    @transactional
    @override
    async def run(self, command: ExecutePhaseCommand) -> ExecutePhaseResult:
        """다음 단계를 실행하거나 기존 시도의 결과를 조회하여 조정한다.

        Args:
            command: run의 소유 범위와 새 실행을 위한 저장 버전.

        Returns:
            ExecutePhaseResult: 커밋할 예약 스냅샷과 동일 시도를 식별하는 ID.
        """
        run = await self.workflows.get(command.run_id)
        run.require_scope(command.project_id, command.session_id)
        phase = run.current
        if phase is None:
            return ExecutePhaseResult(run=run, request_id=None)
        attempt = next(
            (
                item
                for item in reversed(run.attempts)
                if item.phase_key == phase.key
                and item.status in (PhaseStatus.RUNNING, PhaseStatus.WAITING)
            ),
            None,
        )
        fresh = attempt is None
        run.require_task((await self.tasks.get(run.task_id)), recovering=not fresh)
        if attempt is None:
            run.require_revision(command.expected_revision)
            attempt = run.begin()
        run.request_execution(attempt, fresh=fresh)
        saved = await self.workflows.save(run)
        return ExecutePhaseResult(run=saved, request_id=f"{run.uid}:{attempt.number}")

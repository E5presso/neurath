"""실행 가능한 다음 단계를 예약하여 외부 동작 전에 시도를 저장한다."""

from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.repositories.task import ITaskRepository
from neurath.application.ports.repositories.workflow import IWorkflowRepository
from neurath.domain.aggregates.workflow import WorkflowRun


@immutable
class PreparePhaseCommand(AbstractCommand):
    """다음 단계의 실행을 예약할 run과 읽은 저장 버전을 지정한다.

    Attributes:
        project_id: run이 속하는 프로젝트 ID.
        session_id: run을 소유한 세션 ID.
        run_id: 실행할 run ID.
        expected_revision: 예약 전에 읽은 run 저장 버전.
    """

    project_id: UUID
    session_id: UUID
    run_id: UUID
    expected_revision: int


@immutable
class PreparePhaseResult:
    """새 running 시도가 마지막에 추가된 run. 호출자는 저장 후 외부 실행을 연결한다.

    Attributes:
        run: 새 running 시도가 마지막에 추가된 run. 호출자는 저장 후 외부 실행을 연결한다.
    """

    run: WorkflowRun


@UseCase()
class PreparePhaseUseCase(IAsyncCommandUseCase[PreparePhaseCommand, PreparePhaseResult]):
    """실행 가능한 다음 단계를 예약하여 외부 동작 전에 시도를 저장한다.

    활성 태스크의 요구 개정과 run이 맞는지 확인한다. 실행 가능한 첫 단계에
    running 시도를 추가하며, 실제 외부 실행은 이 변경을 커밋한 뒤 수행해야 한다.
    미확정 시도가 있으면 새로 예약하지 않고 기존 결과를 조정해야 한다.
    """

    def __init__(self, workflows: IWorkflowRepository, tasks: ITaskRepository) -> None:
        """태스크와 연결된 절차의 조회·저장 포트를 받는다.

        Args:
            workflows: run의 정의·시도를 조회하고 변경 전체를 저장한다.
            tasks: 태스크의 현재 요구·상태와 소유 범위를 조회한다.
        """
        self.workflows = workflows
        self.tasks = tasks

    @transactional
    @override
    async def run(self, command: PreparePhaseCommand) -> PreparePhaseResult:
        """실행 가능한 다음 단계를 예약하여 외부 동작 전에 시도를 저장한다.

        Args:
            command: 예약할 run ID·소유 범위와 읽은 run revision.

        Returns:
            PreparePhaseResult: 새 running 시도가 마지막에 추가된 run. 호출자는 저장 후 외부 실행을 연결한다.
        """
        run = await self.workflows.get(command.run_id)
        run.require_scope(command.project_id, command.session_id)
        run.require_revision(command.expected_revision)
        run.require_task(await self.tasks.get(run.task_id))
        run.begin()
        return PreparePhaseResult(run=(await self.workflows.save(run)))

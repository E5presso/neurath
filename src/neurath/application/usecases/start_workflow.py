"""선택한 절차를 현재 태스크에 연결하고 첫 실행을 준비한다."""

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
from neurath.domain.values.workflow_definition import WorkflowDefinition


@immutable
class StartWorkflowCommand(AbstractCommand):
    """선택한 스킬 버전·입력·단계를 현재 태스크에 연결하는 요청이다.

    Attributes:
        project_id: run이 속하는 프로젝트 ID.
        session_id: run을 소유한 세션 ID.
        task_id: 절차를 선택할 태스크 ID.
        expected_task_revision: 시작 전에 읽은 태스크 저장 버전.
        definition: 고정할 스킬 버전·입력·순서 있는 단계.
    """

    project_id: UUID
    session_id: UUID
    task_id: UUID
    expected_task_revision: int
    definition: WorkflowDefinition


@immutable
class StartWorkflowResult:
    """새로 연결했거나 같은 정의로 이미 연결된 run. 아직 phase를 실행하지 않는다.

    Attributes:
        run: 새로 연결했거나 같은 정의로 이미 연결된 run. 아직 phase를 실행하지 않는다.
    """

    run: WorkflowRun


@UseCase()
class StartWorkflowUseCase(IAsyncCommandUseCase[StartWorkflowCommand, StartWorkflowResult]):
    """선택한 절차를 현재 태스크에 연결하고 첫 실행을 준비한다.

    이미 같은 정의가 연결돼 있으면 해당 run을 반환한다. 새 run은 태스크의 현재
    시도에 연결하며, 아직 시작하지 않은 태스크는 선행 작업 성공을 확인해 시작한다.
    정의가 다른 기존 run은 덮어쓰지 않고 절차 정정으로 처리하게 한다.
    """

    def __init__(
        self,
        tasks: ITaskRepository,
        workflows: IWorkflowRepository,
    ) -> None:
        """태스크와 연결된 절차의 조회·저장 포트를 받는다.

        Args:
            tasks: 태스크의 현재 요구·상태와 소유 범위를 조회한다.
            workflows: run의 정의·시도를 조회하고 변경 전체를 저장한다.
        """
        self.tasks = tasks
        self.workflows = workflows

    @transactional
    @override
    async def run(self, command: StartWorkflowCommand) -> StartWorkflowResult:
        """선택한 절차를 현재 태스크에 연결하고 첫 실행을 준비한다.

        Args:
            command: 태스크의 소유 범위·읽은 revision과 고정할 절차 정의.

        Returns:
            StartWorkflowResult: 새로 연결했거나 같은 정의로 이미 연결된 run. 아직 phase를 실행하지 않는다.

        Raises:
            InvalidWorkflowState: 다른 정의로 이미 연결된 run을 시작하려 한 경우.
        """
        task = await self.tasks.get(command.task_id)
        task.require_scope(command.project_id, command.session_id)
        existing = await self.workflows.find_by_task_id(task.uid)
        if existing is not None and (
            existing.definition != command.definition
            or existing.revisions[-1].task_definition_number != task.definition.number
        ):
            raise InvalidWorkflowState("Use workflow revision to change an existing procedure")
        if existing is not None:
            return StartWorkflowResult(run=existing)
        task.require_revision(command.expected_task_revision)
        if task.status is not TaskStatus.ACTIVE:
            task.start(await self.tasks.find_by_project_id(command.project_id))
            (await self.tasks.save(task))
        run = WorkflowRun.create(
            command.project_id,
            command.session_id,
            task.uid,
            task.definition.number,
            command.definition,
        )
        return StartWorkflowResult(run=(await self.workflows.save(run)))

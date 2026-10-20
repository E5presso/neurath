"""현재 태스크 요구에 맞춘 절차를 추가하고 영향 없는 단계 결과를 유지한다."""

from dataclasses import dataclass
from typing import override

from spakky.core.pod.annotations.pod import Pod
from spakky.core.stereotype.usecase import UseCase
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.repositories.task import ITaskRepository
from neurath.application.ports.repositories.workflow import IWorkflowRepository
from neurath.domain.aggregates.workflow import WorkflowRun
from neurath.domain.workflow_records import WorkflowDefinition


@dataclass(frozen=True)
class ReviseWorkflowCommand(AbstractCommand):
    """절차를 수정할 정의·입력·대상과 그 이유를 지정한다.

    Attributes:
        project_id: run이 속하는 프로젝트 ID.
        session_id: run을 소유한 세션 ID.
        run_id: 정의를 수정할 run ID.
        expected_revision: 읽은 run 저장 버전.
        definition: 새로 선택한 단계·입력·검증 대상.
        reason: 방법 변경 또는 요구 정정의 이유.
    """

    project_id: str
    session_id: str
    run_id: str
    expected_revision: int
    definition: WorkflowDefinition
    reason: str


@dataclass(frozen=True)
class ReviseWorkflowResult:
    """이전 정의·실패 이력을 보존한 run. 같은 단계 정의의 유효 결과는 재사용한다.

    Attributes:
        run: 이전 정의·실패 이력을 보존한 run. 같은 단계 정의의 유효 결과는 재사용한다.
    """

    run: WorkflowRun


@UseCase(scope=Pod.Scope.CONTEXT)
class ReviseWorkflowUseCase(IAsyncCommandUseCase[ReviseWorkflowCommand, ReviseWorkflowResult]):
    """현재 태스크 요구에 맞춘 절차를 추가하고 영향 없는 단계 결과를 유지한다.

    태스크의 실제 요구 개정에 새 정의를 연결하고 이전 정의·실패를 보존한다.
    대상·조건이 같은 단계는 이전 시도 결과를 재사용한다. 요구 정정 없이
    필수 단계를 삭제하거나 선택 단계로 바꾸는 요청은 거부한다.
    """

    def __init__(self, workflows: IWorkflowRepository, tasks: ITaskRepository) -> None:
        """태스크와 연결된 절차의 조회·저장 포트를 받는다.

        Args:
            workflows: run의 정의·시도를 조회하고 변경 전체를 저장한다.
            tasks: 태스크의 현재 요구·상태와 소유 범위를 조회한다.
        """
        self.workflows = workflows
        self.tasks = tasks

    @override
    async def run(self, command: ReviseWorkflowCommand) -> ReviseWorkflowResult:
        """현재 태스크 요구에 맞춘 절차를 추가하고 영향 없는 단계 결과를 유지한다.

        Args:
            command: 수정할 run의 저장 버전, 새 정의와 변경 이유.

        Returns:
            ReviseWorkflowResult: 이전 정의·실패 이력을 보존한 run. 같은 단계 정의의 유효 결과는 재사용한다.
        """
        run = await self.workflows.get(command.run_id)
        run.require_scope(command.project_id, command.session_id)
        run.require_revision(command.expected_revision)
        task = await self.tasks.get(run.task_id)
        task.require_scope(command.project_id, command.session_id)
        run.revise(command.definition, task.definition.number, command.reason)
        return ReviseWorkflowResult(run=(await self.workflows.save(run)))

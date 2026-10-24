"""선택한 스킬의 절차를 현재 호스트 작업에 연결한다."""

from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.services.skill_catalog import ISkillCatalogService
from neurath.application.usecases.get_task import GetTaskQuery, GetTaskUseCase
from neurath.application.usecases.resolve_session_context import (
    ResolveSessionContextQuery,
    ResolveSessionContextUseCase,
)
from neurath.application.usecases.start_workflow import StartWorkflowCommand, StartWorkflowUseCase
from neurath.domain.aggregates.workflow import WorkflowRun


@immutable
class StartCurrentWorkflowCommand(AbstractCommand):
    """현재 수행할 작업과 에이전트가 선택한 스킬을 지정한다.

    Attributes:
        task_id: 현재 작업 목록의 실제 작업.
        skill: 요청에 맞게 선택한 스킬.
        definition: 명시적으로 전달한 전문 절차 JSON 또는 None.
    """

    task_id: UUID
    skill: str
    definition: str | None = None


@UseCase()
class StartCurrentWorkflowUseCase(IAsyncCommandUseCase[StartCurrentWorkflowCommand, WorkflowRun]):
    """호스트 맥락과 배포 스킬을 찾아 기존 runner를 시작한다."""

    def __init__(
        self,
        context: ResolveSessionContextUseCase,
        tasks: GetTaskUseCase,
        catalog: ISkillCatalogService,
        start: StartWorkflowUseCase,
    ) -> None:
        """관찰·정의 읽기·원장 시작을 분리한 작업 단위를 받는다.

        Args:
            context: 현재 호스트 범위.
            tasks: 현재 작업 개정.
            catalog: 실제 배포 절차.
            start: 기존 runner 시작과 작업 연결.
        """
        self.context = context
        self.tasks = tasks
        self.catalog = catalog
        self.start = start

    @override
    async def run(self, command: StartCurrentWorkflowCommand) -> WorkflowRun:
        """실제 선택한 스킬을 시작하고 수행할 첫 단계를 반환한다.

        Args:
            command: 현재 작업과 선택한 절차.

        Returns:
            WorkflowRun: 상태만 저장한 runner이며 실제 코딩은 호스트가 수행한다.
        """
        scope = await self.context.run(ResolveSessionContextQuery())
        definition = self.catalog.load(
            command.skill, scope.session.working_directory, command.definition
        )
        task = (
            await self.tasks.run(
                GetTaskQuery(
                    project_id=scope.session.project_id,
                    session_id=scope.session.uid,
                    task_id=command.task_id,
                )
            )
        ).task
        return (
            await self.start.run(
                StartWorkflowCommand(
                    project_id=task.project_id,
                    session_id=task.owner_session_id,
                    task_id=task.uid,
                    expected_task_revision=task.revision,
                    definition=definition,
                )
            )
        ).run

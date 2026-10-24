"""회고 제안과 일반 사용자 선택을 기존 스킬의 선택 분기에 기록한다."""

from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.repositories.workflow import IWorkflowRepository
from neurath.domain.aggregates.workflow import WorkflowRun
from neurath.domain.enums.reflection_choice import ReflectionChoice


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

    def __init__(self, workflows: IWorkflowRepository) -> None:
        """기존 절차의 저장 경계를 받는다.

        Args:
            workflows: 사용자 선택을 소유한 실행 저장소.
        """
        self.workflows = workflows

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
        run.choose_reflection(command.choice, command.reason)
        return await self.workflows.save(run)

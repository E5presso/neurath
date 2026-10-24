"""평가 조건·관련 후보·전체 원문을 조회하며 새 실행을 만들지 않는다."""

from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.query import AbstractQuery, IAsyncQueryUseCase

from neurath.application.ports.repositories.workflow import IWorkflowRepository
from neurath.application.ports.services.evaluation_context import (
    EvaluationContext,
    IEvaluationContextService,
)
from neurath.domain.aggregates.workflow import WorkflowRun
from neurath.domain.values.workflow_definition import PhaseDefinition


@immutable
class ReadEvaluationQuery(AbstractQuery):
    """작업 묶음의 평가 단계를 선택한다.

    Attributes:
        project_id: 요청 프로젝트.
        session_id: 실행 소유 세션.
        run_id: 기존 스킬 실행.
        phase_key: 평가할 단계.
    """

    project_id: UUID
    session_id: UUID
    run_id: UUID
    phase_key: str


@immutable
class ReadEvaluationResult:
    """현재 조건과 원문·후보를 실제 배정 전에 반환한다.

    Attributes:
        run: 조회한 실행.
        phase: 선택한 평가 정의.
        context: 실제 전달할 원문과 후보 지문.
    """

    run: WorkflowRun
    phase: PhaseDefinition
    context: EvaluationContext


@UseCase()
class ReadEvaluationUseCase(IAsyncQueryUseCase[ReadEvaluationQuery, ReadEvaluationResult]):
    """현재 후보 조회를 실행 예약·의미 판단과 분리한다."""

    def __init__(self, workflows: IWorkflowRepository, context: IEvaluationContextService) -> None:
        """현재 절차와 원장 조회 계약을 받는다.

        Args:
            workflows: 선택한 실행 조회.
            context: 관련 요구와 전체 맥락 구성.
        """
        self.workflows = workflows
        self.context = context

    @transactional
    @override
    async def run(self, query: ReadEvaluationQuery) -> ReadEvaluationResult:
        """소유 범위를 확인하고 선택한 평가 단계의 현재 자료를 반환한다.

        Args:
            query: 기존 실행과 평가 단계.

        Returns:
            ReadEvaluationResult: 현재 조건·맥락이며 실행 성공을 뜻하지 않는다.
        """
        run = await self.workflows.get(query.run_id)
        run.require_scope(query.project_id, query.session_id)
        phase = run.evaluation_phase(query.phase_key)
        return ReadEvaluationResult(
            run=run, phase=phase, context=await self.context.load(run, phase)
        )

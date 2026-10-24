"""평가 조건·관련 후보·전체 원문을 조회하며 새 실행을 만들지 않는다."""

import json
from hashlib import sha256
from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.domain.application.query import AbstractQuery, IAsyncQueryUseCase

from neurath.application.ports.services.evaluation_artifact import IEvaluationArtifactService
from neurath.application.ports.services.evaluation_context import (
    EvaluationContext,
)
from neurath.application.usecases.read_evaluation import ReadEvaluationQuery, ReadEvaluationUseCase
from neurath.domain.aggregates.workflow import WorkflowRun
from neurath.domain.values.workflow_definition import PhaseDefinition


@immutable
class GetEvaluationQuery(AbstractQuery):
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
class GetEvaluationResult:
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
class GetEvaluationUseCase(IAsyncQueryUseCase[GetEvaluationQuery, GetEvaluationResult]):
    """짧은 DB 스냅샷을 닫은 뒤 파일·Git을 관찰하여 현재 후보를 구성한다."""

    def __init__(self, read: ReadEvaluationUseCase, artifacts: IEvaluationArtifactService) -> None:
        """원장 조회와 외부 관찰의 독립 경계를 받는다.

        Args:
            read: 원문·작업·단계의 짧은 읽기 요청.
            artifacts: DB 트랜잭션 밖에서 파일과 Git을 관찰한다.
        """
        self.read = read
        self.artifacts = artifacts

    @override
    async def run(self, query: GetEvaluationQuery) -> GetEvaluationResult:
        """외부 관찰 동안 DB 연결을 점유하지 않고 후보 지문을 반환한다.

        Args:
            query: 실제 평가할 기존 실행과 단계.

        Returns:
            GetEvaluationResult: 원장 스냅샷과 실제 외부 관찰에 연결된 후보.
        """
        snapshot = await self.read.run(
            ReadEvaluationQuery(
                project_id=query.project_id,
                session_id=query.session_id,
                run_id=query.run_id,
                phase_key=query.phase_key,
            )
        )
        target = snapshot.phase.evaluation
        assert target is not None
        observed = await self.artifacts.observe(
            snapshot.phase.directory, (*target.artifacts, *target.verification)
        )
        candidate = sha256(
            json.dumps((snapshot.context.candidate, tuple(observed)), sort_keys=True).encode()
        ).hexdigest()
        context = EvaluationContext(
            candidate=candidate,
            requirements=snapshot.context.candidate,
            scope=snapshot.context.scope
            + f"\nObserved candidate: {json.dumps(tuple(observed), ensure_ascii=False)}",
        )
        return GetEvaluationResult(run=snapshot.run, phase=snapshot.phase, context=context)

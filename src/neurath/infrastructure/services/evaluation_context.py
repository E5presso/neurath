"""기존 SQLAlchemy 원장에서 독립 평가의 실제 원문과 후보 지문을 구성한다."""

import hashlib
import json
from dataclasses import asdict
from typing import override

from spakky.core.pod.annotations.pod import Pod

from neurath.application.ports.services.evaluation_artifact import IEvaluationArtifactService
from neurath.application.ports.services.evaluation_context import (
    EvaluationContext,
    IEvaluationContextService,
)
from neurath.domain.aggregates.workflow import WorkflowRun
from neurath.domain.errors import InvalidWorkflowState
from neurath.domain.values.workflow_definition import PhaseDefinition
from neurath.infrastructure.repositories.request_source import SQLAlchemyRequestSourceRepository
from neurath.infrastructure.repositories.task import SQLAlchemyTaskRepository
from neurath.serialization import encode_uuid


@Pod()
class SQLAlchemyEvaluationContextService(IEvaluationContextService):
    """평가 이력·상태 변경을 지문에서 제외하고 관련 요구·자료만 대조한다."""

    def __init__(
        self,
        tasks: SQLAlchemyTaskRepository,
        sources: SQLAlchemyRequestSourceRepository,
        artifacts: IEvaluationArtifactService,
    ) -> None:
        """현재 요청의 SQLAlchemy 저장소를 받는다.

        Args:
            tasks: 전체 TODO와 관련 요구를 조회한다.
            sources: 최초 원문과 정정 이력을 조회한다.
            artifacts: 실제 파일 내용과 현재 HEAD를 관찰한다.
        """
        self.tasks = tasks
        self.sources = sources
        self.artifacts = artifacts

    @override
    async def load(self, run: WorkflowRun, phase: PhaseDefinition) -> EvaluationContext:
        """실제 원문·전체 TODO와 관련 후보의 내용 지문을 구성한다.

        Args:
            run: 평가를 소유한 작업 절차.
            phase: 관련 작업·산출물·검증 자료를 지정한 평가 단계.

        Returns:
            EvaluationContext: 관련 변경만 반영한 지문과 전체 전달 본문.

        Raises:
            InvalidWorkflowState: 평가 정의가 없거나 관련 작업이 같은 세션에 없는 경우.
        """
        target = phase.evaluation
        if target is None:
            raise InvalidWorkflowState("Phase has no independent evaluation target")
        tasks = tuple(
            task
            for task in await self.tasks.find_by_project_id(run.project_id)
            if task.owner_session_id == run.session_id
        )
        selected = set(target.task_ids) | {run.task_id}
        related = tuple(task for task in tasks if task.uid in selected)
        if {task.uid for task in related} != selected:
            raise InvalidWorkflowState("Evaluation scope contains unavailable work")
        originals = {}
        for task in tasks:
            source = await self.sources.get(task.definition.source_id)
            originals[source.uid] = source.body
            while source.corrects_id is not None:
                source = await self.sources.get(source.corrects_id)
                originals[source.uid] = source.body
        observed = await self.artifacts.observe(
            phase.directory, (*target.artifacts, *target.verification)
        )
        payload = json.dumps(
            {
                "target": phase.target_revision,
                "purpose": phase.purpose,
                "checks": phase.checks,
                "observed": observed,
                "evaluation": asdict(target),
                "requirements": [(task.uid, asdict(task.definition)) for task in related],
            },
            default=encode_uuid,
            sort_keys=True,
            ensure_ascii=False,
        )
        return EvaluationContext(
            candidate=hashlib.sha256(payload.encode()).hexdigest(),
            scope=f"""Independent {target.kind} evaluation; candidate {phase.target_revision}.
Evaluation purpose: {phase.purpose}
Required checks: {json.dumps(phase.checks, ensure_ascii=False)}
Original user sources and corrections (source IDs retain their provenance):
{chr(10).join(f"Source {uid}: {body}" for uid, body in originals.items())}
Full current TODO, including incomplete and failed work:
{chr(10).join(f"{task.uid} / definition {task.definition.number} / {task.status}: {task.definition.title}; required: {task.definition.required_result}" for task in tasks)}
Current observed candidate: {json.dumps(observed, ensure_ascii=False)}
Actual artifacts: {json.dumps(target.artifacts, ensure_ascii=False)}
Verification and problem evidence: {json.dumps(target.verification, ensure_ascii=False)}
Compare original intent, latest corrections and actual artifacts, including requirements omitted from TODO and out-of-scope changes.
Report concrete evidence and unmet items. Suggestions are not new user instructions.
Do not complete the owner's tasks, publish externally, or recursively delegate evaluation.""",
        )

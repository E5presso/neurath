"""현재 작업의 스킬 절차를 시작하고 방법·단계 결과·회고 선택을 연결한다."""

import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, cast
from uuid import UUID

from spakky.plugins.sqlalchemy.persistency.connection_manager import AsyncConnectionManager
from spakky.plugins.typer.stereotypes.cli_controller import CliController, command
from typer import Option, echo

from neurath.application.usecases.choose_reflection import (
    ChooseReflectionCommand,
    ChooseReflectionUseCase,
)
from neurath.application.usecases.consume_evaluation import (
    ConsumeEvaluationCommand,
    ConsumeEvaluationUseCase,
)
from neurath.application.usecases.get_workflow import GetWorkflowQuery, GetWorkflowUseCase
from neurath.application.usecases.report_phase import ReportPhaseCommand, ReportPhaseUseCase
from neurath.application.usecases.resolve_session_context import (
    ResolveSessionContextQuery,
    ResolveSessionContextUseCase,
)
from neurath.application.usecases.revise_workflow import (
    ReviseWorkflowCommand,
    ReviseWorkflowUseCase,
)
from neurath.application.usecases.start_current_workflow import (
    StartCurrentWorkflowCommand,
    StartCurrentWorkflowUseCase,
)
from neurath.domain.aggregates.workflow import WorkflowRun
from neurath.domain.enums.reflection_choice import ReflectionChoice
from neurath.domain.values.evaluation_target import EvaluationKind, EvaluationTarget
from neurath.domain.values.phase_attempt import PhaseResult, PhaseStatus
from neurath.domain.values.workflow_definition import PhaseDefinition, WorkflowDefinition
from neurath.serialization import encode_uuid


@CliController("workflow")
class WorkflowCliController:
    """에이전트가 호스트 도구로 수행한 절차를 같은 runner에 보고한다."""

    def __init__(
        self,
        context: ResolveSessionContextUseCase,
        start: StartCurrentWorkflowUseCase,
        read: GetWorkflowUseCase,
        report: ReportPhaseUseCase,
        revise: ReviseWorkflowUseCase,
        reflection: ChooseReflectionUseCase,
        consume: ConsumeEvaluationUseCase,
        connection: AsyncConnectionManager,
    ) -> None:
        """절차의 시작·조회·관찰 결과·정정 작업 단위를 받는다.

        Args:
            context: 현재 호스트 범위.
            start: 선택한 스킬 시작.
            read: 현재 절차와 개정 조회.
            report: 호스트 수행 결과 반영.
            revise: 같은 목표의 수행 방법 정정.
            reflection: 요청·철회한 회고 선택.
            consume: 실제 독립 평가 보고 수용.
            connection: 명령 이벤트 루프 정리.
        """
        self.context = context
        self.start = start
        self.read = read
        self.report = report
        self.revise = revise
        self.reflection = reflection
        self.consume = consume
        self.connection = connection

    @staticmethod
    def _output(run: WorkflowRun) -> None:
        """다음 단계와 실제 남은 상태를 읽기 쉬운 JSON으로 출력한다.

        Args:
            run: 저장된 현재 절차.
        """
        echo(
            json.dumps(
                {
                    "id": run.uid,
                    "task_id": run.task_id,
                    "revision": run.revision,
                    "skill": run.definition.skill,
                    "definition": asdict(run.definition),
                    "attempts": [asdict(attempt) for attempt in run.attempts],
                    "current": None if run.current is None else asdict(run.current),
                    "reflection": run.reflection,
                    "steps_complete": run.current is None,
                },
                default=encode_uuid,
                ensure_ascii=False,
            )
        )

    @command("start")
    async def start_workflow(
        self,
        task_id: Annotated[UUID, Option("--task-id")],
        skill: Annotated[str, Option("--skill")],
        definition: Annotated[
            str | None, Option("--definition", help="전문 절차 JSON; -는 stdin, @경로는 파일")
        ] = None,
    ) -> None:
        """현재 작업에 요청에 맞게 선택한 실제 스킬 절차를 연결한다.

        Args:
            task_id: 현재 작업 목록에서 선택한 작업.
            skill: 선택한 기본 또는 전문 스킬 이름.
            definition: 전문 절차 JSON 또는 기본 스킬을 고를 None.
        """
        try:
            content = definition
            if definition == "-":
                content = sys.stdin.read()
            elif definition is not None and definition.startswith("@"):
                content = Path(definition[1:]).read_text()
            self._output(
                await self.start.run(
                    StartCurrentWorkflowCommand(task_id=task_id, skill=skill, definition=content)
                )
            )
        finally:
            await self.connection.dispose()

    @command("show")
    async def show_workflow(self, run_id: Annotated[UUID, Option("--run-id")]) -> None:
        """패키지·스킬 파일이 바뀌어도 기존 고정 정의와 시도를 변경 없이 읽는다.

        Args:
            run_id: 현재 세션이 소유한 기존 실행.
        """
        try:
            scope = await self.context.run(ResolveSessionContextQuery())
            self._output(
                (
                    await self.read.run(
                        GetWorkflowQuery(
                            project_id=scope.session.project_id,
                            session_id=scope.session.uid,
                            run_id=run_id,
                        )
                    )
                ).run
            )
        finally:
            await self.connection.dispose()

    @command("report")
    async def report_step(
        self,
        run_id: Annotated[UUID, Option("--run-id")],
        summary: Annotated[str, Option("--summary")],
        reference: Annotated[list[str], Option("--reference")],
        check: list[str] | None = None,
        status: PhaseStatus = PhaseStatus.SUCCEEDED,
        accepted: Annotated[bool | None, Option("--accepted/--rejected")] = None,
    ) -> None:
        """호스트에서 실제 수행한 현재 단계 또는 독립 평가의 판단을 보고한다.

        Args:
            run_id: 현재 작업의 절차.
            summary: 실제 수행 결과 또는 평가 수용·기각 이유.
            reference: 실제 수행과 판단의 근거.
            check: 실제 확인한 조건만 반복 지정한다.
            status: 일반 단계의 관찰 결과.
            accepted: 독립 평가 결과의 근거 있는 수용·기각.

        Raises:
            ValueError: 현재 단계가 없거나 평가를 일반 결과로 통과시키려는 경우.
        """
        try:
            scope = await self.context.run(ResolveSessionContextQuery())
            run = (
                await self.read.run(
                    GetWorkflowQuery(
                        project_id=scope.session.project_id,
                        session_id=scope.session.uid,
                        run_id=run_id,
                    )
                )
            ).run
            phase = run.current
            if phase is None:
                raise ValueError("All workflow steps already have results")
            if phase.evaluation is not None:
                if accepted is None:
                    raise ValueError(
                        "Read the actual independent report and explicitly accept or reject its findings"
                    )
                self._output(
                    await self.consume.run(
                        ConsumeEvaluationCommand(
                            project_id=run.project_id,
                            session_id=run.session_id,
                            run_id=run.uid,
                            phase_key=phase.key,
                            accepted=accepted,
                            rationale=summary,
                            references=reference,
                        )
                    )
                )
                return
            self._output(
                (
                    await self.report.run(
                        ReportPhaseCommand(
                            project_id=run.project_id,
                            session_id=run.session_id,
                            run_id=run.uid,
                            attempt_number=None,
                            result=PhaseResult(
                                status=status,
                                target_revision=phase.target_revision,
                                summary=summary,
                                evidence=reference,
                                checks=() if check is None else check,
                            ),
                        )
                    )
                ).run
            )
        finally:
            await self.connection.dispose()

    @command("revise")
    async def revise_workflow(
        self,
        run_id: Annotated[UUID, Option("--run-id")],
        reason: Annotated[str, Option("--reason")],
        definition: str | None = None,
        reflection: ReflectionChoice | None = None,
    ) -> None:
        """원 목표를 바꾸지 않는 방법 변경 또는 사용자의 회고 선택을 반영한다.

        Args:
            run_id: 정정할 현재 절차.
            reason: 실제 방법 변경 또는 사용자 선택의 근거.
            definition: 변경할 단계 배열 JSON이며 -는 stdin.
            reflection: 한 번의 제안·요청·거절·무응답 선택.

        Raises:
            ValueError: 방법 변경과 선택을 동시에 섞거나 정의가 배열이 아닌 경우.
        """
        try:
            if (definition is None) == (reflection is None):
                raise ValueError("Supply either a revised definition or a reflection choice")
            scope = await self.context.run(ResolveSessionContextQuery())
            run = (
                await self.read.run(
                    GetWorkflowQuery(
                        project_id=scope.session.project_id,
                        session_id=scope.session.uid,
                        run_id=run_id,
                    )
                )
            ).run
            if reflection is not None:
                self._output(
                    await self.reflection.run(
                        ChooseReflectionCommand(
                            project_id=run.project_id,
                            session_id=run.session_id,
                            run_id=run.uid,
                            choice=reflection,
                            reason=reason,
                        )
                    )
                )
                return
            raw = json.load(sys.stdin) if definition == "-" else json.loads(cast(str, definition))
            if not isinstance(raw, list):
                raise ValueError("Workflow definition must be an array of phase objects")
            phases = []
            for item in raw:
                evaluation = item.get("evaluation")
                phases.append(
                    PhaseDefinition(
                        key=item["key"],
                        purpose=item["purpose"],
                        directory=scope.session.working_directory,
                        arguments=item.get("arguments", ()),
                        target_revision=item.get("target_revision", "current"),
                        checks=item.get("checks", ("done",)),
                        skip_condition=item.get("skip_condition"),
                        evaluation=None
                        if evaluation is None
                        else EvaluationTarget(
                            kind=EvaluationKind(evaluation["kind"]),
                            artifacts=evaluation.get("artifacts", ()),
                            verification=evaluation.get("verification", ()),
                        ),
                    )
                )
            self._output(
                (
                    await self.revise.run(
                        ReviseWorkflowCommand(
                            project_id=run.project_id,
                            session_id=run.session_id,
                            run_id=run.uid,
                            expected_revision=run.revision,
                            definition=WorkflowDefinition(
                                skill=run.definition.skill,
                                version=run.definition.version,
                                phases=tuple(phases),
                                inputs=run.definition.inputs,
                            ),
                            reason=reason,
                        )
                    )
                ).run
            )
        finally:
            await self.connection.dispose()

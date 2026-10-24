"""수행 위임과 현재 절차의 독립 평가를 같은 협업 요청에 연결한다."""

from collections.abc import Sequence
from dataclasses import replace
from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.usecases.delegate_task import DelegateTaskCommand, DelegateTaskUseCase
from neurath.application.usecases.discover_provider import (
    DiscoverProviderQuery,
    DiscoverProviderUseCase,
)
from neurath.application.usecases.prepare_delegation import PrepareDelegationCommand
from neurath.application.usecases.read_result_context import (
    ReadResultContextQuery,
    ReadResultContextUseCase,
)
from neurath.application.usecases.request_evaluation import (
    RequestEvaluationCommand,
    RequestEvaluationUseCase,
)
from neurath.application.usecases.revise_workflow import (
    ReviseWorkflowCommand,
    ReviseWorkflowUseCase,
)
from neurath.domain.aggregates.delegation import Delegation
from neurath.domain.enums.delegation_role import DelegationRole
from neurath.domain.values.evaluation_target import EvaluationTarget


@immutable
class DispatchWorkAssignmentCommand(AbstractCommand):
    """현재 소유 작업의 배정과 실제 평가 자료를 전달한다.

    Attributes:
        project_id: 현재 프로젝트.
        session_id: 원 작업 소유 세션.
        assignment: 실제 수신 경로·범위·역할.
        artifacts: 현재 평가할 산출물.
        verification: 실제 검증·문제 관찰 자료.
    """

    project_id: UUID
    session_id: UUID
    assignment: PrepareDelegationCommand
    artifacts: Sequence[str] = ()
    verification: Sequence[str] = ()


@UseCase()
class DispatchWorkAssignmentUseCase(
    IAsyncCommandUseCase[DispatchWorkAssignmentCommand, Delegation]
):
    """정의·자료 검증을 마친 뒤 기존 절차와 실제 위임 경로를 연결한다."""

    def __init__(
        self,
        read: ReadResultContextUseCase,
        delegate: DelegateTaskUseCase,
        discover: DiscoverProviderUseCase,
        revise: ReviseWorkflowUseCase,
        evaluate: RequestEvaluationUseCase,
    ) -> None:
        """짧은 원장 요청과 외부 모델 조회를 각각 담당할 계약을 받는다.

        Args:
            read: 현재 작업과 절차 스냅샷.
            delegate: 일반 수행·검토 위임.
            discover: 실제 지원 모델과 정책의 읽기 조회.
            revise: 실제 산출물 참조를 현재 평가 단계에 연결한다.
            evaluate: 검증된 후보의 독립 평가를 요청한다.
        """
        self.read = read
        self.delegate = delegate
        self.discover = discover
        self.revise = revise
        self.evaluate = evaluate

    @override
    async def run(self, command: DispatchWorkAssignmentCommand) -> Delegation:
        """실제 후보가 있는 평가 단계만 runner에 연결하고 나머지는 원 위임으로 보낸다.

        Args:
            command: 원 작업 범위와 실제 위임 입력.

        Returns:
            Delegation: 실행 성공과 구분되는 실제 저장 배정.

        Raises:
            ValueError: 현재 provider가 선택한 모델·정책을 지원하지 않는 경우.
        """
        assignment = command.assignment
        work = await self.read.run(
            ReadResultContextQuery(
                project_id=command.project_id,
                session_id=command.session_id,
                task_id=assignment.task_id,
            )
        )
        flow = work.workflow
        phase = None if flow is None else flow.current
        if (
            assignment.role is not DelegationRole.REVIEWER
            or flow is None
            or phase is None
            or phase.evaluation is None
        ):
            return await self.delegate.run(DelegateTaskCommand(assignment=assignment))
        target = EvaluationTarget(
            kind=phase.evaluation.kind,
            task_ids=phase.evaluation.task_ids,
            artifacts=command.artifacts,
            verification=command.verification,
        )
        target.require_ready()
        if assignment.plan is not None:
            supported = await self.discover.run(
                DiscoverProviderQuery(provider=assignment.plan.provider)
            )
            if (
                assignment.plan.model not in supported.models
                or assignment.plan.policy not in supported.policies
            ):
                raise ValueError(
                    "The installed provider does not support the selected model or policy"
                )
        changed = replace(phase, evaluation=target)
        definition = replace(
            flow.definition,
            phases=tuple(
                changed if item.key == phase.key else item for item in flow.definition.phases
            ),
        )
        flow = (
            await self.revise.run(
                ReviseWorkflowCommand(
                    project_id=flow.project_id,
                    session_id=flow.session_id,
                    run_id=flow.uid,
                    expected_revision=flow.revision,
                    definition=definition,
                    reason="Attach actual result and verification to the selected evaluation phase",
                )
            )
        ).run
        return await self.evaluate.run(
            RequestEvaluationCommand(
                project_id=flow.project_id,
                session_id=flow.session_id,
                run_id=flow.uid,
                phase_key=phase.key,
                sender_id=assignment.sender_id,
                route=assignment.route,
                recipient_id=assignment.recipient_id,
                plan=assignment.plan,
                retry_of=assignment.retry_of,
            )
        )

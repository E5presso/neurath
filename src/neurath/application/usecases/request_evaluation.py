"""현재 후보의 독립 평가를 기존 협업 경로로 한 번 요청한다."""

from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.usecases.bind_evaluation import (
    BindEvaluationCommand,
    BindEvaluationUseCase,
)
from neurath.application.usecases.discover_provider import (
    DiscoverProviderQuery,
    DiscoverProviderUseCase,
)
from neurath.application.usecases.dispatch_delegation import (
    DispatchDelegationCommand,
    DispatchDelegationUseCase,
)
from neurath.application.usecases.get_delegation import GetDelegationQuery, GetDelegationUseCase
from neurath.application.usecases.get_evaluation import GetEvaluationQuery, GetEvaluationUseCase
from neurath.application.usecases.prepare_delegation import (
    PrepareDelegationCommand,
    PrepareDelegationUseCase,
)
from neurath.application.usecases.start_provider import StartProviderCommand, StartProviderUseCase
from neurath.domain.aggregates.delegation import Delegation
from neurath.domain.enums.delegation_role import DelegationRole
from neurath.domain.enums.delegation_route import DelegationRoute
from neurath.domain.values.provider_plan import ProviderPlan


@immutable
class RequestEvaluationCommand(AbstractCommand):
    """독립 평가의 현재 후보와 실제 수신 경로를 지정한다.

    Attributes:
        project_id: 요청 프로젝트.
        session_id: 실행 소유 세션.
        run_id: 마무리할 기존 스킬 실행.
        phase_key: 해당 실행의 평가 단계.
        sender_id: 실제 실행자 피어.
        route: 실제 피어·자식·provider 경로.
        recipient_id: 관찰한 수신 피어이며 provider 시작 전에는 None.
        plan: 명시적으로 선택한 provider 모델·정책.
    """

    project_id: UUID
    session_id: UUID
    run_id: UUID
    phase_key: str
    sender_id: UUID
    route: DelegationRoute
    recipient_id: UUID | None = None
    plan: ProviderPlan | None = None


@UseCase()
class RequestEvaluationUseCase(IAsyncCommandUseCase[RequestEvaluationCommand, Delegation]):
    """현재 입력 조회·배정·phase 연결 커밋 후에만 실제 외부 실행을 시작한다."""

    def __init__(
        self,
        read: GetEvaluationUseCase,
        prepare: PrepareDelegationUseCase,
        bind: BindEvaluationUseCase,
        dispatch: DispatchDelegationUseCase,
        discover: DiscoverProviderUseCase,
        start: StartProviderUseCase,
        delegation: GetDelegationUseCase,
    ) -> None:
        """기존 유스케이스의 독립 트랜잭션과 외부 실행 경계를 받는다.

        Args:
            read: 평가할 현재 맥락을 조회한다.
            prepare: 기존 협업 배정을 준비한다.
            bind: 평가 시도와 배정을 커밋한다.
            dispatch: 피어 배정을 전달한다.
            discover: 실제 지원 모델과 정책을 조회한다.
            start: 커밋 후 provider 실행을 요청한다.
            delegation: 후속 실행의 실제 저장 결과를 조회한다.
        """
        self.read = read
        self.prepare = prepare
        self.bind = bind
        self.dispatch = dispatch
        self.discover = discover
        self.start = start
        self.delegation = delegation

    @override
    async def run(self, command: RequestEvaluationCommand) -> Delegation:
        """같은 후보의 기존 배정을 재사용하며 실패·대기를 자동 재실행하지 않는다.

        Args:
            command: 현재 실행·평가 단계와 실제 수신 경로.

        Returns:
            Delegation: 실제 관찰한 배정 상태이며 요청만으로 성공하지 않는다.

        Raises:
            ValueError: 실제 지원하지 않는 모델·정책을 지정한 경우.
        """
        evaluation = await self.read.run(
            GetEvaluationQuery(
                project_id=command.project_id,
                session_id=command.session_id,
                run_id=command.run_id,
                phase_key=command.phase_key,
            )
        )
        evaluation.run.require_evaluation(evaluation.phase)
        previous = evaluation.run.latest(evaluation.phase)
        if (
            previous is not None
            and previous.delegation_id is not None
            and previous.candidate == evaluation.context.candidate
        ):
            existing = await self.delegation.run(
                GetDelegationQuery(delegation_id=previous.delegation_id, peer_id=command.sender_id)
            )
            if existing.message_id is not None or existing.provider_requested:
                return existing
            return await self._dispatch(existing, command.sender_id)
        if command.plan is not None:
            capabilities = await self.discover.run(
                DiscoverProviderQuery(provider=command.plan.provider)
            )
            if (
                command.plan.model not in capabilities.models
                or command.plan.policy not in capabilities.policies
            ):
                raise ValueError("The installed provider does not support this model or policy")
        assignment = await self.prepare.run(
            PrepareDelegationCommand(
                task_id=evaluation.run.task_id,
                sender_id=command.sender_id,
                role=DelegationRole.REVIEWER,
                scope=evaluation.context.scope,
                candidate=evaluation.context.candidate,
                route=command.route,
                recipient_id=command.recipient_id,
                plan=command.plan,
            )
        )
        await self.bind.run(
            BindEvaluationCommand(
                project_id=command.project_id,
                session_id=command.session_id,
                run_id=command.run_id,
                phase_key=command.phase_key,
                delegation_id=assignment.uid,
            )
        )
        return await self._dispatch(assignment, command.sender_id)

    async def _dispatch(self, assignment: Delegation, sender_id: UUID) -> Delegation:
        """커밋 후 미전달 배정을 이어가고 원 실행의 실제 상태를 조회한다.

        Args:
            assignment: 단계에 연결하고 커밋한 원 배정.
            sender_id: 원 실행자 피어.

        Returns:
            Delegation: 전달·실행 요청 이후 실제 저장 상태.
        """
        if assignment.plan is None:
            await self.dispatch.run(
                DispatchDelegationCommand(delegation_id=assignment.uid, sender_id=sender_id)
            )
        else:
            await self.start.run(
                StartProviderCommand(delegation_id=assignment.uid, sender_id=sender_id)
            )
        return await self.delegation.run(
            GetDelegationQuery(delegation_id=assignment.uid, peer_id=sender_id)
        )

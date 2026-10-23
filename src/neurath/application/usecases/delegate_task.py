"""사용자의 기존 작업을 실제 피어 또는 검증된 독립 provider에 배정한다."""

from dataclasses import dataclass
from typing import override

from spakky.core.stereotype.usecase import UseCase
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.usecases.discover_provider import (
    DiscoverProviderQuery,
    DiscoverProviderUseCase,
)
from neurath.application.usecases.dispatch_delegation import (
    DispatchDelegationCommand,
    DispatchDelegationUseCase,
)
from neurath.application.usecases.get_delegation import GetDelegationQuery, GetDelegationUseCase
from neurath.application.usecases.prepare_delegation import (
    PrepareDelegationCommand,
    PrepareDelegationUseCase,
)
from neurath.application.usecases.start_provider import StartProviderCommand, StartProviderUseCase
from neurath.domain.aggregates.delegation import Delegation


@dataclass(frozen=True)
class DelegateTaskCommand(AbstractCommand):
    """기존 작업과 명시한 수신 경로를 실제 배정할 요청이다.

    Attributes:
        assignment: 원 태스크·역할·범위·수신자·선택적 실행 계획.
    """

    assignment: PrepareDelegationCommand


@UseCase()
class DelegateTaskUseCase(IAsyncCommandUseCase[DelegateTaskCommand, Delegation]):
    """모델 확인·배정 저장·커밋 후 실행과 최종 결과 조회를 작업 단위로 연결한다."""

    def __init__(
        self,
        discover: DiscoverProviderUseCase,
        prepare: PrepareDelegationUseCase,
        dispatch: DispatchDelegationUseCase,
        start: StartProviderUseCase,
        read: GetDelegationUseCase,
    ) -> None:
        """각 독립 작업 단위의 유스케이스를 받으며 외부 트랜잭션을 덧씌우지 않는다.

        Args:
            discover: 추론 없이 실제 지원 모델·정책을 확인한다.
            prepare: 원 태스크와 범위를 검증해 계획을 저장한다.
            dispatch: 피어에게 기존 배정 메시지를 전달한다.
            start: 검증된 계획을 커밋 후 외부 실행으로 연결한다.
            read: 예약 응답을 완료로 오해하지 않도록 저장 상태를 읽는다.
        """
        self.discover = discover
        self.prepare = prepare
        self.dispatch = dispatch
        self.start = start
        self.read = read

    @override
    async def run(self, command: DelegateTaskCommand) -> Delegation:
        """명시한 계획과 수신 경로를 그대로 적용하고 관찰된 상태만 반환한다.

        Args:
            command: 원 태스크에 연결한 배정 요청.

        Returns:
            Delegation: 원 배정의 실제 저장 상태. 준비·수락·완료를 구분한다.

        Raises:
            ValueError: 실제 지원하지 않는 모델·정책을 요청한 경우.
        """
        assignment = command.assignment
        if assignment.plan is not None:
            capabilities = await self.discover.run(DiscoverProviderQuery(assignment.plan.provider))
            if (
                assignment.plan.model not in capabilities.models
                or assignment.plan.policy not in capabilities.policies
            ):
                raise ValueError("The installed provider does not support this model or policy")
        delegation = await self.prepare.run(assignment)
        if assignment.plan is None:
            await self.dispatch.run(DispatchDelegationCommand(delegation.uid, assignment.sender_id))
        else:
            await self.start.run(StartProviderCommand(delegation.uid, assignment.sender_id))
        return await self.read.run(GetDelegationQuery(delegation.uid, assignment.sender_id))

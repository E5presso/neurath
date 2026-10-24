"""기존 동료·provider 실행을 유한하게 기다리며 새 모델 실행은 만들지 않는다."""

import asyncio
from time import monotonic
from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.usecases.get_delegation import GetDelegationQuery, GetDelegationUseCase
from neurath.application.usecases.recover_provider import (
    RecoverProviderCommand,
    RecoverProviderUseCase,
)
from neurath.domain.aggregates.delegation import Delegation
from neurath.domain.enums.delegation_status import DelegationStatus
from neurath.domain.enums.provider_status import ProviderStatus


@immutable
class ObserveDelegationCommand(AbstractCommand):
    """실제 원 배정의 조회와 요청 안의 유한 대기를 지정한다.

    Attributes:
        delegation_id: 기존 배정.
        peer_id: 실제 참가자.
        wait_seconds: 모델 재호출 없이 기다릴 최대 초.
    """

    delegation_id: UUID
    peer_id: UUID
    wait_seconds: float = 0


@UseCase()
class ObserveDelegationUseCase(IAsyncCommandUseCase[ObserveDelegationCommand, Delegation]):
    """DB 트랜잭션을 유지하지 않고 같은 실행의 실제 상태만 관찰한다."""

    def __init__(self, read: GetDelegationUseCase, recover: RecoverProviderUseCase) -> None:
        """원 배정의 조회와 외부 결과 반영 경로를 받는다.

        Args:
            read: 원 배정과 참가자 확인.
            recover: 같은 provider 실행의 실제 관찰과 저장.
        """
        self.read = read
        self.recover = recover

    @override
    async def run(self, command: ObserveDelegationCommand) -> Delegation:
        """완료 또는 유한 대기 종료까지 기존 실행을 조회한다.

        Args:
            command: 원 배정과 대기 한도.

        Returns:
            Delegation: 관찰한 원 보고·실패·대기 상태.

        Raises:
            ValueError: 대기 시간이 지원 범위를 벗어난 경우.
        """
        if not 0 <= command.wait_seconds <= 300:
            raise ValueError("Wait must be between 0 and 300 seconds")
        deadline = monotonic() + command.wait_seconds
        while True:
            assignment = await self.read.run(
                GetDelegationQuery(delegation_id=command.delegation_id, peer_id=command.peer_id)
            )
            if assignment.provider_requested:
                await self.recover.run(
                    RecoverProviderCommand(delegation_id=assignment.uid, peer_id=command.peer_id)
                )
                assignment = await self.read.run(
                    GetDelegationQuery(delegation_id=assignment.uid, peer_id=command.peer_id)
                )
            if (
                assignment.status is DelegationStatus.STOPPED
                or assignment.report is not None
                or assignment.provider_status
                in (ProviderStatus.COMPLETED, ProviderStatus.FAILED, ProviderStatus.STOPPED)
                or monotonic() >= deadline
            ):
                return assignment
            await asyncio.sleep(min(1, max(0, deadline - monotonic())))

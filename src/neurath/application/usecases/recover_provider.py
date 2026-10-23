"""재연결 시 원 실행의 실제 자료만 대조해 저장하고 새 실행은 만들지 않는다."""

import asyncio
from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase
from spakky.event.event_publisher import IAsyncEventPublisher

from neurath.application.ports.services.provider import IProviderService
from neurath.application.provider_records import ProviderObservation
from neurath.application.usecases.get_delegation import GetDelegationQuery, GetDelegationUseCase
from neurath.domain.collaboration_events import ProviderExecutionObserved
from neurath.domain.errors import InvalidTaskState


@immutable
class RecoverProviderCommand(AbstractCommand):
    """원 배정의 실행만 복구 조회할 참가자를 지정한다.

    Attributes:
        delegation_id: 원 배정 ID.
        peer_id: 발신자 또는 실제 수신자.
    """

    delegation_id: UUID
    peer_id: UUID


@UseCase()
class RecoverProviderUseCase(IAsyncCommandUseCase[RecoverProviderCommand, ProviderObservation]):
    """원 실행을 조회하고 취소 대상이면 실제 중단을 요청한 뒤 관찰을 보존한다."""

    def __init__(
        self,
        read: GetDelegationUseCase,
        provider: IProviderService,
        publisher: IAsyncEventPublisher,
    ) -> None:
        """범위 조회와 원 실행 관찰 계약을 받는다.

        Args:
            read: 원 배정의 참가자와 계획을 확인한다.
            provider: 기존 실행 관찰·실제 중단을 담당한다.
            publisher: 관찰을 별도 저장 유스케이스로 전달한다.
        """
        self.read = read
        self.provider = provider
        self.publisher = publisher

    @override
    async def run(self, command: RecoverProviderCommand) -> ProviderObservation:
        """기존 실행만 조회하며 불명 상태를 재실행이나 중단 성공으로 승격하지 않는다.

        Args:
            command: 원 배정과 참가자.

        Returns:
            ProviderObservation: 저장을 요청한 실제 관찰. 최종 DB 상태는 다시 조회한다.

        Raises:
            InvalidTaskState: 실행 요청이 없는 배정인 경우.
        """
        delegation = await self.read.run(
            GetDelegationQuery(delegation_id=command.delegation_id, peer_id=command.peer_id)
        )
        if not delegation.provider_requested:
            raise InvalidTaskState("No provider execution to recover")
        result = await asyncio.to_thread(
            self.provider.cancel if delegation.stop_reason is not None else self.provider.observe,
            delegation.uid,
        )
        await self.publisher.publish(
            ProviderExecutionObserved(
                delegation_id=delegation.uid,
                reference=result.reference,
                status=result.status,
                native_session_id=result.native_session_id,
                output=result.output,
                error=result.error,
            )
        )
        return result

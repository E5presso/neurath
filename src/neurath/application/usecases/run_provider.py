"""커밋된 계획을 실제 CLI 실행으로 연결하고 초기 관찰을 후속 저장에 전달한다."""

import asyncio
from dataclasses import dataclass
from typing import override

from spakky.core.stereotype.usecase import UseCase
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase
from spakky.event.event_publisher import IAsyncEventPublisher

from neurath.application.ports.services.provider import IProviderService
from neurath.application.provider_records import ProviderObservation
from neurath.application.usecases.check_provider_start import (
    CheckProviderStartQuery,
    CheckProviderStartUseCase,
)
from neurath.domain.collaboration_events import ProviderExecutionObserved
from neurath.domain.errors import InvalidTaskState


@dataclass(frozen=True)
class RunProviderCommand(AbstractCommand):
    """커밋된 배정의 실행 입력이다.

    Attributes:
        delegation_id: 실행할 원 배정.
        prompt: 원 지시와 맡긴 범위.
    """

    delegation_id: str
    prompt: str


@UseCase()
class RunProviderUseCase(IAsyncCommandUseCase[RunProviderCommand, None]):
    """최신 배정을 다시 확인한 뒤 DB 트랜잭션 밖에서 원 실행을 시작한다."""

    def __init__(
        self,
        check: CheckProviderStartUseCase,
        provider: IProviderService,
        publisher: IAsyncEventPublisher,
    ) -> None:
        """현재 배정 조회·실제 실행·관찰 발행 계약을 받는다.

        Args:
            check: 원 요구 정정·취소 여부를 읽는다.
            provider: 고유 배정 ID의 외부 실행을 시작한다.
            publisher: 실제 관찰을 새 트랜잭션으로 전달한다.
        """
        self.check = check
        self.provider = provider
        self.publisher = publisher

    @override
    async def run(self, command: RunProviderCommand) -> None:
        """고정 계획만 실행하며 모델·정책 오류를 다른 설정으로 대체하지 않는다.

        Args:
            command: 저장된 원 배정과 입력.

        Raises:
            InvalidTaskState: 커밋된 실행 계획이나 요청이 없는 경우.
        """
        delegation = await self.check.run(CheckProviderStartQuery(command.delegation_id))
        if delegation.plan is None or not delegation.provider_requested:
            raise InvalidTaskState("Provider execution was not requested")
        try:
            result = await asyncio.to_thread(
                self.provider.start, delegation.uid, delegation.plan, command.prompt
            )
        except Exception as error:
            result = ProviderObservation("", "unknown", error=f"{type(error).__name__}: {error}")
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

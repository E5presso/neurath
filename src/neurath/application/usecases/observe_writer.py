"""실제 작성 호출의 생존을 관찰하고 원래 임대 세대와 함께 발행한다."""

import asyncio
from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase
from spakky.event.event_publisher import IAsyncEventPublisher

from neurath.application.ports.services.writer_observer import IWriterObserverService
from neurath.application.usecases.read_native_liveness import (
    ReadNativeLivenessQuery,
    ReadNativeLivenessUseCase,
)
from neurath.domain.enums.liveness import Liveness
from neurath.domain.events.writer_liveness_observed import WriterLivenessObserved


@immutable
class ObserveWriterCommand(AbstractCommand):
    """이미 커밋된 요청의 실제 호스트 대상을 지정한다.

    Attributes:
        writer_id: 관찰할 작성 임대.
        execution_id: 관찰 당시 소유 실행.
        turn_id: 관찰할 실제 턴.
        tool_use_id: 정확한 작성 도구 호출.
        generation: 결과 저장 시 대조할 세대.
    """

    writer_id: UUID
    execution_id: UUID
    turn_id: str
    tool_use_id: str
    generation: int


@UseCase()
class ObserveWriterUseCase(IAsyncCommandUseCase[ObserveWriterCommand, None]):
    """실제 작성 호출의 생존을 관찰하고 원래 임대 세대와 함께 발행한다."""

    def __init__(
        self,
        native: ReadNativeLivenessUseCase,
        observer: IWriterObserverService,
        publisher: IAsyncEventPublisher,
    ) -> None:
        """실제 호스트 서비스와 관찰 결과 발행자를 받는다.

        Args:
            native: 요청 간 보존된 실제 호스트 사건을 읽는다.
            observer: 직접 관리 중인 프로세스가 있을 때 실제 종료를 관찰한다.
            publisher: 관찰 결과를 후속 저장 유스케이스에 전달한다.
        """
        self.observer = observer
        self.native = native
        self.publisher = publisher

    @override
    async def run(self, command: ObserveWriterCommand) -> None:
        """DB 트랜잭션 없이 호스트를 호출하고 결과를 원래 요청에 연결한다.

        Args:
            command: 실제 대상 식별자와 재검사할 요청 범위.
        """
        live = await self.native.run(
            ReadNativeLivenessQuery(
                execution_id=command.execution_id,
                turn_id=command.turn_id,
                tool_use_id=command.tool_use_id,
            )
        )
        if live is Liveness.UNKNOWN:
            live = await asyncio.to_thread(
                self.observer.observe, command.execution_id, command.turn_id, command.tool_use_id
            )
        await self.publisher.publish(
            WriterLivenessObserved(
                writer_id=command.writer_id,
                execution_id=command.execution_id,
                generation=command.generation,
                liveness=live,
            )
        )

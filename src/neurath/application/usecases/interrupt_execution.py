"""실제 실행의 중단을 요청하고 호스트 관찰 결과를 발행한다."""

import asyncio
from dataclasses import dataclass
from typing import override

from spakky.core.stereotype.usecase import UseCase
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase
from spakky.event.event_publisher import IAsyncEventPublisher

from neurath.application.ports.services.execution_controller import IExecutionControllerService
from neurath.domain.runtime_events import ExecutionInterruptionObserved


@dataclass(frozen=True)
class InterruptExecutionCommand(AbstractCommand):
    """이미 커밋된 요청의 실제 호스트 대상을 지정한다.

    Attributes:
        execution_id: 중단할 실제 실행.
        turn_id: 중단할 정확한 호스트 턴.
    """

    execution_id: str
    turn_id: str


@UseCase()
class InterruptExecutionUseCase(IAsyncCommandUseCase[InterruptExecutionCommand, None]):
    """실제 실행의 중단을 요청하고 호스트 관찰 결과를 발행한다."""

    def __init__(
        self, controller: IExecutionControllerService, publisher: IAsyncEventPublisher
    ) -> None:
        """실제 호스트 서비스와 관찰 결과 발행자를 받는다.

        Args:
            controller: 요청에 지정한 실제 호스트 대상을 관찰한다.
            publisher: 관찰 결과를 후속 저장 유스케이스에 전달한다.
        """
        self.controller = controller
        self.publisher = publisher

    @override
    async def run(self, command: InterruptExecutionCommand) -> None:
        """DB 트랜잭션 없이 호스트를 호출하고 결과를 원래 요청에 연결한다.

        Args:
            command: 실제 대상 식별자와 재검사할 요청 범위.
        """
        live = await asyncio.to_thread(
            self.controller.interrupt, command.execution_id, command.turn_id
        )
        await self.publisher.publish(
            ExecutionInterruptionObserved(
                execution_id=command.execution_id, turn_id=command.turn_id, liveness=live
            )
        )

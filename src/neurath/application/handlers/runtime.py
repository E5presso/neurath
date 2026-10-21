"""커밋된 요청의 실제 호스트 상태를 관찰한 뒤 후속 유스케이스를 호출한다."""

import asyncio

from spakky.event.stereotype.event_handler import EventHandler, on_event

from neurath.application.ports.services.execution_controller import IExecutionControllerService
from neurath.application.ports.services.writer_observer import IWriterObserverService
from neurath.application.usecases.confirm_cancellation import (
    ConfirmCancellationCommand,
    ConfirmCancellationUseCase,
)
from neurath.application.usecases.release_writer import ReleaseWriterCommand, ReleaseWriterUseCase
from neurath.domain.runtime_events import ExecutionCancellationRequested, WriterRecoveryRequested


@EventHandler()
class RuntimeEventHandler:
    """DB 트랜잭션 밖에서 중단·종료 관찰을 하고 별도 트랜잭션으로 확정한다."""

    def __init__(
        self,
        controller: IExecutionControllerService,
        observer: IWriterObserverService,
        cancellation: ConfirmCancellationUseCase,
        release: ReleaseWriterUseCase,
    ) -> None:
        """호스트 관찰과 결과 저장의 의존성을 받는다.

        Args:
            controller: 실제 실행의 중단과 종료를 확인한다.
            observer: 정확한 작성 호출의 생존을 관찰한다.
            cancellation: 최신 턴을 대조하여 중단을 확정한다.
            release: 최신 소유자·세대를 대조하여 임대를 해제한다.
        """
        self.controller = controller
        self.observer = observer
        self.cancellation = cancellation
        self.release = release

    @on_event(ExecutionCancellationRequested)
    async def cancel(self, event: ExecutionCancellationRequested) -> None:
        """추가 쓰기 중지 커밋 뒤 호스트를 중단하고 실제 결과를 기록한다.

        Args:
            event: 중단할 실제 실행과 턴.
        """
        live = await asyncio.to_thread(self.controller.interrupt, event.execution_id, event.turn_id)
        await self.cancellation.run(
            ConfirmCancellationCommand(event.execution_id, event.turn_id, live)
        )

    @on_event(WriterRecoveryRequested)
    async def recover(self, event: WriterRecoveryRequested) -> None:
        """관찰 중 바뀐 임대를 해제하지 않도록 저장된 소유자·세대를 함께 전달한다.

        Args:
            event: 조회할 호출과 회수 요청 당시 임대 세대.
        """
        live = await asyncio.to_thread(
            self.observer.observe, event.execution_id, event.turn_id, event.tool_use_id
        )
        await self.release.run(
            ReleaseWriterCommand(event.writer_id, event.execution_id, event.generation, live)
        )

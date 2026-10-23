"""실행·작성 사건을 각 작업을 담당하는 유스케이스로 전달한다."""

from spakky.event.stereotype.event_handler import EventHandler, on_event

from neurath.application.usecases.confirm_cancellation import (
    ConfirmCancellationCommand,
    ConfirmCancellationUseCase,
)
from neurath.application.usecases.interrupt_execution import (
    InterruptExecutionCommand,
    InterruptExecutionUseCase,
)
from neurath.application.usecases.observe_writer import ObserveWriterCommand, ObserveWriterUseCase
from neurath.application.usecases.release_writer import ReleaseWriterCommand, ReleaseWriterUseCase
from neurath.domain.runtime_events import (
    ExecutionCancellationRequested,
    ExecutionInterruptionObserved,
    WriterLivenessObserved,
    WriterRecoveryRequested,
)


@EventHandler()
class RuntimeEventHandler:
    """호스트 관찰과 원장 반영의 사건을 독립적인 유스케이스 호출로 변환한다."""

    def __init__(
        self,
        interruption: InterruptExecutionUseCase,
        observation: ObserveWriterUseCase,
        cancellation: ConfirmCancellationUseCase,
        release: ReleaseWriterUseCase,
    ) -> None:
        """각 사건을 처리할 유스케이스만 주입받는다.

        Args:
            interruption: 실제 호스트에 중단을 요청한다.
            observation: 실제 작성 호출의 생존을 관찰한다.
            cancellation: 관찰 결과로 현재 턴의 중단을 확정한다.
            release: 관찰 결과와 현재 소유자·세대로 임대를 해제한다.
        """
        self.interruption = interruption
        self.observation = observation
        self.cancellation = cancellation
        self.release = release

    @on_event(ExecutionCancellationRequested)
    async def cancel(self, event: ExecutionCancellationRequested) -> None:
        """중단 요청 사건을 실제 호스트 작업의 입력으로 변환한다.

        Args:
            event: 중단할 실행과 정확한 턴.
        """
        await self.interruption.run(
            InterruptExecutionCommand(execution_id=event.execution_id, turn_id=event.turn_id)
        )

    @on_event(WriterRecoveryRequested)
    async def recover(self, event: WriterRecoveryRequested) -> None:
        """회수 요청 사건을 생존 관찰 입력으로 변환한다.

        Args:
            event: 관찰할 실제 호출과 재검사할 소유 세대.
        """
        await self.observation.run(
            ObserveWriterCommand(
                writer_id=event.writer_id,
                execution_id=event.execution_id,
                turn_id=event.turn_id,
                tool_use_id=event.tool_use_id,
                generation=event.generation,
            )
        )

    @on_event(ExecutionInterruptionObserved)
    async def confirm(self, event: ExecutionInterruptionObserved) -> None:
        """중단 관찰을 저장 유스케이스의 입력으로 변환한다.

        Args:
            event: 정확한 턴의 실제 중단 관찰.
        """
        await self.cancellation.run(
            ConfirmCancellationCommand(
                execution_id=event.execution_id, turn_id=event.turn_id, liveness=event.liveness
            )
        )

    @on_event(WriterLivenessObserved)
    async def release_writer(self, event: WriterLivenessObserved) -> None:
        """생존 관찰과 원래 세대를 해제 유스케이스의 입력으로 변환한다.

        Args:
            event: 관찰 결과와 재검사할 소유자·세대.
        """
        await self.release.run(
            ReleaseWriterCommand(
                writer_id=event.writer_id,
                execution_id=event.execution_id,
                generation=event.generation,
                liveness=event.liveness,
            )
        )

"""대상 턴을 먼저 정지시키고 실제 실행기의 중단 확인을 같은 턴에만 적용한다."""

from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.repositories.execution import IExecutionRepository
from neurath.domain.aggregates.execution import Execution


@immutable
class CancelExecutionCommand(AbstractCommand):
    """사용자가 중단을 요청한 실행과 턴을 지정한다.

    Attributes:
        execution_id: 중단할 실행의 내부 ID.
        turn_id: 현재 호스트에서 확인한 중단 대상 턴.
    """

    execution_id: UUID
    turn_id: str


@UseCase()
class CancelExecutionUseCase(IAsyncCommandUseCase[CancelExecutionCommand, Execution]):
    """현재 턴을 paused로 보존하고 커밋 뒤 호스트 중단을 요청한다.

    실제 종료 확인은 RuntimeEventHandler와 ConfirmCancellationUseCase가 담당한다.
    요청 응답을 cancelled 판정으로 사용하지 않으며 최신 실행 상태를 조회한다.
    """

    def __init__(self, executions: IExecutionRepository) -> None:
        """현재 상태와 후속 관찰 요청을 저장할 저장소를 받는다.

        Args:
            executions: 실제 소유 상태를 조회하고 요청을 기록한다.
        """
        self.executions = executions

    @transactional
    @override
    async def run(self, command: CancelExecutionCommand) -> Execution:
        """대상 턴을 확인하고 추가 쓰기 중지와 중단 요청 이벤트를 함께 저장한다.

        Args:
            command: 중단할 실행과 실제 호스트 턴.

        Returns:
            Execution: 요청 시점의 상태이며 종료 확인을 뜻하지 않는다.
        """
        current = await self.executions.get(command.execution_id)
        current.request_cancellation(command.turn_id)
        return await self.executions.save(current)

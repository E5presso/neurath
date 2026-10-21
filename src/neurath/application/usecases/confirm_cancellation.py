"""호스트 관찰 이후 현재 소유 상태를 재검사하여 확정 결과만 반영한다."""

from dataclasses import dataclass
from typing import override

from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.repositories.execution import IExecutionRepository
from neurath.domain.aggregates.execution import Execution
from neurath.domain.runtime_records import Liveness


@dataclass(frozen=True)
class ConfirmCancellationCommand(AbstractCommand):
    """외부 조회와 대조할 소유 식별자와 실제 관찰을 전달한다.

    Attributes:
        execution_id: 결과를 반영할 원장의 식별자.
        turn_id: 관찰한 실행의 정확한 턴.
        liveness: 실제 호스트에서 관찰한 종료 상태.
    """

    execution_id: str
    turn_id: str
    liveness: Liveness


@UseCase()
class ConfirmCancellationUseCase(IAsyncCommandUseCase[ConfirmCancellationCommand, Execution]):
    """호스트 조회 중 변경된 소유자·턴·세대를 덮어쓰지 않고 관찰을 반영한다."""

    def __init__(self, executions: IExecutionRepository) -> None:
        """최신 상태를 재조회하고 저장할 저장소를 받는다.

        Args:
            executions: 상태 재검사와 결과 저장을 수행한다.
        """
        self.executions = executions

    @transactional
    @override
    async def run(self, command: ConfirmCancellationCommand) -> Execution:
        """최신 상태를 읽고 관찰한 대상과 일치할 때 결과를 반영한다.

        Args:
            command: 관찰한 대상과 실제 호스트 결과.

        Returns:
            Execution: 결과가 반영된 현재 원장.
        """
        current = await self.executions.get(command.execution_id)
        current.require_turn(command.turn_id)
        if command.liveness is Liveness.STOPPED:
            current.cancel(command.turn_id, "Host confirmed execution termination")
        return await self.executions.save(current)

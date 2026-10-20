"""대상 턴을 먼저 정지시키고 실제 실행기의 중단 확인을 같은 턴에만 적용한다."""

import asyncio
from dataclasses import dataclass
from typing import override

from spakky.core.pod.annotations.pod import Pod
from spakky.core.stereotype.usecase import UseCase
from spakky.data.persistency.transaction import AbstractAsyncTransaction
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.repositories.execution import IExecutionRepository
from neurath.application.ports.services.execution_controller import IExecutionControllerService
from neurath.domain.aggregates.execution import Execution
from neurath.domain.runtime_records import Liveness


@dataclass(frozen=True)
class CancelExecutionCommand(AbstractCommand):
    """사용자가 중단을 요청한 실행과 턴을 지정한다.

    Attributes:
        execution_id: 중단할 실행의 내부 ID.
        turn_id: 현재 호스트에서 확인한 중단 대상 턴.
    """

    execution_id: str
    turn_id: str


@UseCase(scope=Pod.Scope.CONTEXT)
class CancelExecutionUseCase(IAsyncCommandUseCase[CancelExecutionCommand, Execution]):
    """새 작성은 즉시 막고 외부 실행의 실제 중단 확인 후 취소를 기록한다.

    외부 호출 동안 DB 트랜잭션을 유지하지 않는다. 응답이 늦어 새 턴이 열렸다면
    그 턴을 취소하지 않는다. 중단 요청이 유실되거나 실패하면 paused를 보존한다.
    """

    def __init__(
        self,
        executions: IExecutionRepository,
        controller: IExecutionControllerService,
        transaction: AbstractAsyncTransaction,
    ) -> None:
        """실행 저장소와 실제 중단 어댑터, 표준 트랜잭션을 받는다.

        Args:
            executions: 중단 전후 대상 턴을 대조하는 저장소.
            controller: 해당 실행만 중단하고 결과를 확인하는 호스트 어댑터.
            transaction: 외부 호출 전후의 독립된 저장 경계.
        """
        self.executions = executions
        self.controller = controller
        self.transaction = transaction

    @override
    async def run(self, command: CancelExecutionCommand) -> Execution:
        """지정 턴의 추가 실행을 막은 뒤 실제 중단을 요청·확인한다.

        Args:
            command: 사용자 중단 요청의 정확한 실행과 턴.

        Returns:
            Execution: 실제 중단이 확인되면 cancelled, 아니면 paused인 실행.
        """
        async with self.transaction:
            before = await self.executions.get(command.execution_id)
            before.require_turn(command.turn_id)
            before.pause("Cancellation requested; actual termination is pending")
            before = await self.executions.save(before)
        live = await asyncio.to_thread(self.controller.interrupt, before)
        async with self.transaction:
            current = await self.executions.get(command.execution_id)
            current.require_turn(command.turn_id)
            if live is Liveness.STOPPED:
                current.cancel(command.turn_id, "Host confirmed execution termination")
            return await self.executions.save(current)

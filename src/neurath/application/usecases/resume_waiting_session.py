"""해소된 원 작업에 연결된 정상 대기와 피어 활성 상태를 함께 조정한다."""

from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.repositories.execution import IExecutionRepository
from neurath.application.ports.repositories.peer import IPeerRepository
from neurath.application.ports.repositories.task import ITaskRepository
from neurath.domain.enums.task_status import TaskStatus


@immutable
class ResumeWaitingSessionCommand(AbstractCommand):
    """대기가 실제로 해소된 원 작업을 지정한다.

    Attributes:
        task_id: 같은 실행 시도로 돌아온 작업.
    """

    task_id: UUID


@UseCase()
class ResumeWaitingSessionUseCase(IAsyncCommandUseCase[ResumeWaitingSessionCommand, None]):
    """Task의 대기 해소가 Execution과 협업 피어에 남은 정지를 함께 해소한다."""

    def __init__(
        self, tasks: ITaskRepository, executions: IExecutionRepository, peers: IPeerRepository
    ) -> None:
        """같은 소유 작업에 연결된 원장만 조회·변경한다.

        Args:
            tasks: 현재 작업 상태 확인.
            executions: 정상 대기 원인 확인과 해소.
            peers: 관련 실행의 협업 활성 상태.
        """
        self.tasks = tasks
        self.executions = executions
        self.peers = peers

    @transactional
    @override
    async def run(self, command: ResumeWaitingSessionCommand) -> None:
        """후속 취소·정정이 없는 정상 대기만 해소한다.

        Args:
            command: 커밋된 TaskResumed 사건의 원 작업.
        """
        task = await self.tasks.get(command.task_id)
        if task.status is not TaskStatus.ACTIVE:
            return
        for execution in await self.executions.find_by_session_id(task.owner_session_id):
            if execution.agent_id or not execution.resume_waiting():
                continue
            await self.executions.save(execution)
            peer = await self.peers.find_by_session_id_and_agent_id(
                task.owner_session_id, execution.agent_id
            )
            if peer is not None:
                peer.active = True
                await self.peers.save(peer)

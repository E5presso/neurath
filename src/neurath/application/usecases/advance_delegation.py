"""수락된 최신 배정의 실제 진행을 기록하고 정정·취소 후 실행을 거부한다."""

from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.repositories.delegation import IDelegationRepository
from neurath.application.ports.repositories.task import ITaskRepository
from neurath.domain.aggregates.delegation import Delegation


@immutable
class AdvanceDelegationCommand(AbstractCommand):
    """수락된 최신 배정의 실제 진행을 기록하고 정정·취소 후 실행을 거부한다.

    Attributes:
        delegation_id: 수락·보고할 원 배정 ID.
        peer_id: 호출한 등록 피어.
        observation: 실제 시작·진행·검사의 관찰 근거.
    """

    delegation_id: UUID
    peer_id: UUID
    observation: str


@UseCase()
class AdvanceDelegationUseCase(IAsyncCommandUseCase[AdvanceDelegationCommand, Delegation]):
    """수락된 최신 배정의 실제 진행을 기록하고 정정·취소 후 실행을 거부한다."""

    def __init__(self, delegations: IDelegationRepository, tasks: ITaskRepository) -> None:
        """요청 범위의 조회·저장 계약을 받는다.

        Args:
            delegations: Delegation aggregate의 범위 조회와 저장.
            tasks: Task aggregate의 범위 조회와 저장.
        """
        self.delegations = delegations
        self.tasks = tasks

    @transactional
    @override
    async def run(self, command: AdvanceDelegationCommand) -> Delegation:
        """수락된 최신 배정의 실제 진행을 기록하고 정정·취소 후 실행을 거부한다.

        Args:
            command: 원문·수신 범위와 해당 작업에 필요한 입력.

        Returns:
            Delegation: 요청한 범위에서 저장 또는 조회한 결과.
        """
        delegation = await self.delegations.get(command.delegation_id)
        delegation.advance(
            command.peer_id, await self.tasks.get(delegation.task_id), command.observation
        )
        return await self.delegations.save(delegation)

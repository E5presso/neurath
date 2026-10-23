"""수신자가 기존 사용자 지시에 연결된 최신 배정을 추가 승인 없이 수락한다."""

from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.repositories.delegation import IDelegationRepository
from neurath.application.ports.repositories.peer import IPeerRepository
from neurath.application.ports.repositories.task import ITaskRepository
from neurath.domain.aggregates.delegation import Delegation


@immutable
class AcceptDelegationCommand(AbstractCommand):
    """수신자가 기존 사용자 지시에 연결된 최신 배정을 추가 승인 없이 수락한다.

    Attributes:
        delegation_id: 수락·보고할 원 배정 ID.
        peer_id: 호출한 등록 피어.
    """

    delegation_id: UUID
    peer_id: UUID


@UseCase()
class AcceptDelegationUseCase(IAsyncCommandUseCase[AcceptDelegationCommand, Delegation]):
    """수신자가 기존 사용자 지시에 연결된 최신 배정을 추가 승인 없이 수락한다."""

    def __init__(
        self, delegations: IDelegationRepository, tasks: ITaskRepository, peers: IPeerRepository
    ) -> None:
        """요청 범위의 조회·저장 계약을 받는다.

        Args:
            delegations: Delegation aggregate의 범위 조회와 저장.
            tasks: Task aggregate의 범위 조회와 저장.
            peers: 현재 수신자의 실행 배정 연결을 저장한다.
        """
        self.delegations = delegations
        self.peers = peers
        self.tasks = tasks

    @transactional
    @override
    async def run(self, command: AcceptDelegationCommand) -> Delegation:
        """수신자가 기존 사용자 지시에 연결된 최신 배정을 추가 승인 없이 수락한다.

        Args:
            command: 원문·수신 범위와 해당 작업에 필요한 입력.

        Returns:
            Delegation: 요청한 범위에서 저장 또는 조회한 결과.
        """
        delegation = await self.delegations.get(command.delegation_id)
        delegation.accept(command.peer_id, await self.tasks.get(delegation.task_id))
        peer = await self.peers.get(command.peer_id)
        peer.accept_assignment(delegation.uid)
        await self.peers.save(peer)
        return await self.delegations.save(delegation)

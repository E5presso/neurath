"""실제 중단 관찰을 원 배정에 기록하며 취소 요청만으로 종료를 추정하지 않는다."""

from dataclasses import dataclass
from typing import override

from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.repositories.delegation import IDelegationRepository
from neurath.application.ports.repositories.peer import IPeerRepository
from neurath.domain.aggregates.delegation import Delegation


@dataclass(frozen=True)
class ConfirmDelegationStopCommand(AbstractCommand):
    """실제 중단 관찰을 원 배정에 기록하며 취소 요청만으로 종료를 추정하지 않는다.

    Attributes:
        delegation_id: 수락·보고할 원 배정 ID.
        peer_id: 호출한 등록 피어.
        evidence: 수신 경계에서 확인한 실제 중단의 근거.
    """

    delegation_id: str
    peer_id: str
    evidence: str


@UseCase()
class ConfirmDelegationStopUseCase(IAsyncCommandUseCase[ConfirmDelegationStopCommand, Delegation]):
    """실제 중단 관찰을 원 배정에 기록하며 취소 요청만으로 종료를 추정하지 않는다."""

    def __init__(self, delegations: IDelegationRepository, peers: IPeerRepository) -> None:
        """요청 범위의 조회·저장 계약을 받는다.

        Args:
            delegations: Delegation aggregate의 범위 조회와 저장.
            peers: 현재 수신자의 실행 배정 연결을 저장한다.
        """
        self.delegations = delegations
        self.peers = peers

    @transactional
    @override
    async def run(self, command: ConfirmDelegationStopCommand) -> Delegation:
        """실제 중단 관찰을 원 배정에 기록하며 취소 요청만으로 종료를 추정하지 않는다.

        Args:
            command: 원문·수신 범위와 해당 작업에 필요한 입력.

        Returns:
            Delegation: 요청한 범위에서 저장 또는 조회한 결과.
        """
        delegation = await self.delegations.get(command.delegation_id)
        delegation.confirm_stop(command.peer_id, command.evidence)
        peer = await self.peers.get(command.peer_id)
        peer.finish_assignment(delegation.uid)
        await self.peers.save(peer)
        return await self.delegations.save(delegation)

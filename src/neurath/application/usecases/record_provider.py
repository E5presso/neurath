"""실제 provider 출력에서만 수신 세션을 연결하고 원 실행 결과를 저장한다."""

from dataclasses import dataclass
from typing import override

from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.repositories.delegation import IDelegationRepository
from neurath.application.ports.repositories.peer import IPeerRepository
from neurath.application.ports.repositories.session import ISessionRepository
from neurath.application.ports.repositories.task import ITaskRepository
from neurath.application.ports.services.provider import ProviderObservation
from neurath.domain.aggregates.delegation import Delegation
from neurath.domain.aggregates.peer import Peer
from neurath.domain.aggregates.session import HostSession


@dataclass(frozen=True)
class RecordProviderCommand(AbstractCommand):
    """실제 provider 출력에서만 수신 세션을 연결하고 원 실행 결과를 저장한다.

    Attributes:
        delegation_id: 수락·보고할 원 배정 ID.
        observation: 실제 원 실행에서 읽은 관찰.
    """

    delegation_id: str
    observation: ProviderObservation


@UseCase()
class RecordProviderUseCase(IAsyncCommandUseCase[RecordProviderCommand, Delegation]):
    """실제 provider 출력에서만 수신 세션을 연결하고 원 실행 결과를 저장한다."""

    def __init__(
        self,
        delegations: IDelegationRepository,
        tasks: ITaskRepository,
        sessions: ISessionRepository,
        peers: IPeerRepository,
    ) -> None:
        """요청 범위의 조회·저장 계약을 받는다.

        Args:
            delegations: Delegation aggregate의 범위 조회와 저장.
            tasks: Task aggregate의 범위 조회와 저장.
            sessions: Session aggregate의 범위 조회와 저장.
            peers: Peer aggregate의 범위 조회와 저장.
        """
        self.delegations = delegations
        self.tasks = tasks
        self.sessions = sessions
        self.peers = peers

    @transactional
    @override
    async def run(self, command: RecordProviderCommand) -> Delegation:
        """실제 provider 출력에서만 수신 세션을 연결하고 원 실행 결과를 저장한다.

        Args:
            command: 원문·수신 범위와 해당 작업에 필요한 입력.

        Returns:
            Delegation: 요청한 범위에서 저장 또는 조회한 결과.
        """
        delegation = await self.delegations.get(command.delegation_id)
        delegation.reconcile(await self.tasks.get(delegation.task_id))
        observation = command.observation
        delegation.observe_provider(
            observation.reference,
            observation.status,
            observation.native_session_id,
            observation.output,
            observation.error,
        )
        if observation.native_session_id is not None and delegation.plan is not None:
            parent = await self.sessions.get(delegation.plan.parent_session_id)
            session = await self.sessions.find_by_project_id_and_provider_and_host_session_id(
                parent.project_id, delegation.plan.provider, observation.native_session_id
            )
            if session is None:
                session = await self.sessions.save(
                    HostSession.create(
                        parent.project_id,
                        delegation.plan.provider,
                        observation.native_session_id,
                        delegation.plan.directory,
                    )
                )
            peer = await self.peers.find_by_session_id_and_agent_id(session.uid, "")
            if peer is None:
                peer = Peer(uid=Peer.next_id(), session_id=session.uid)
            peer.active = delegation.provider_status == "running"
            delegation.bind_provider_peer(
                delegation.plan.provider, observation.native_session_id, peer.uid
            )
            if peer.active:
                peer.accept_assignment(delegation.uid)
            else:
                peer.finish_assignment(delegation.uid)
            await self.peers.save(peer)
        return await self.delegations.save(delegation)

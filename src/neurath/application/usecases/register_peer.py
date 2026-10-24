"""관찰된 호스트 실행의 주소를 등록하고 재연결 때 같은 피어를 재사용한다."""

from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.repositories.execution import IExecutionRepository
from neurath.application.ports.repositories.peer import IPeerRepository
from neurath.application.ports.repositories.session import ISessionRepository
from neurath.domain.aggregates.peer import Peer
from neurath.domain.enums.execution_status import ExecutionStatus
from neurath.domain.errors import ContextNotFound


@immutable
class RegisterPeerCommand(AbstractCommand):
    """관찰된 호스트 실행의 주소를 등록하고 재연결 때 같은 피어를 재사용한다.

    Attributes:
        session_id: 호출한 실제 세션.
        agent_id: 실제 네이티브 자식 ID이며 루트면 빈 문자열.
    """

    session_id: UUID
    agent_id: str = ""


@UseCase()
class RegisterPeerUseCase(IAsyncCommandUseCase[RegisterPeerCommand, Peer]):
    """관찰된 호스트 실행의 주소를 등록하고 재연결 때 같은 피어를 재사용한다."""

    def __init__(
        self, sessions: ISessionRepository, executions: IExecutionRepository, peers: IPeerRepository
    ) -> None:
        """요청 범위의 조회·저장 계약을 받는다.

        Args:
            sessions: Session aggregate의 범위 조회와 저장.
            executions: Execution aggregate의 범위 조회와 저장.
            peers: Peer aggregate의 범위 조회와 저장.
        """
        self.sessions = sessions
        self.executions = executions
        self.peers = peers

    @transactional
    @override
    async def run(self, command: RegisterPeerCommand) -> Peer:
        """관찰된 호스트 실행의 주소를 등록하고 재연결 때 같은 피어를 재사용한다.

        Args:
            command: 원문·수신 범위와 해당 작업에 필요한 입력.

        Returns:
            Peer: 요청한 범위에서 저장 또는 조회한 결과.

        Raises:
            ContextNotFound: 요청한 피어·발신자·대화가 지정된 소유 범위와 다른 경우.
        """
        session = await self.sessions.get(command.session_id)
        session.require_current_owner()
        execution = await self.executions.find_by_session_id_and_agent_id(
            command.session_id, command.agent_id
        )
        if execution is None:
            raise ContextNotFound("Register the actual host execution before registering its peer")
        peer = await self.peers.find_by_session_id_and_agent_id(
            command.session_id, command.agent_id
        )
        if peer is None:
            peer = Peer(
                uid=Peer.next_id(), session_id=command.session_id, agent_id=command.agent_id
            )
        peer.active = execution.status is ExecutionStatus.RUNNING
        return await self.peers.save(peer)

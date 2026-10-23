"""기존 배정의 최신 요구를 검증·커밋한 뒤 독립 실행을 요청한다."""

from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.repositories.delegation import IDelegationRepository
from neurath.application.ports.repositories.peer import IPeerRepository
from neurath.application.ports.repositories.request_source import IRequestSourceRepository
from neurath.application.ports.repositories.session import ISessionRepository
from neurath.application.ports.repositories.task import ITaskRepository
from neurath.domain.aggregates.delegation import Delegation
from neurath.domain.errors import ContextNotFound


@immutable
class StartProviderCommand(AbstractCommand):
    """기존 배정의 최신 요구를 검증·커밋한 뒤 독립 실행을 요청한다.

    Attributes:
        delegation_id: 수락·보고할 원 배정 ID.
        sender_id: 배정 책임이 있는 발신 피어.
    """

    delegation_id: UUID
    sender_id: UUID


@UseCase()
class StartProviderUseCase(IAsyncCommandUseCase[StartProviderCommand, Delegation]):
    """기존 배정의 최신 요구를 검증·커밋한 뒤 독립 실행을 요청한다."""

    def __init__(
        self,
        delegations: IDelegationRepository,
        tasks: ITaskRepository,
        sources: IRequestSourceRepository,
        peers: IPeerRepository,
        sessions: ISessionRepository,
    ) -> None:
        """요청 범위의 조회·저장 계약을 받는다.

        Args:
            delegations: Delegation aggregate의 범위 조회와 저장.
            tasks: Task aggregate의 범위 조회와 저장.
            sources: 원 지시와 정정 원문.
            peers: 배정 발신자의 실제 세션 소유 상태를 확인한다.
            sessions: 배정 발신자의 실제 세션 소유 상태를 확인한다.
        """
        self.delegations = delegations
        self.sessions = sessions
        self.peers = peers
        self.tasks = tasks
        self.sources = sources

    @transactional
    @override
    async def run(self, command: StartProviderCommand) -> Delegation:
        """기존 배정의 최신 요구를 검증·커밋한 뒤 독립 실행을 요청한다.

        Args:
            command: 원문·수신 범위와 해당 작업에 필요한 입력.

        Returns:
            Delegation: 요청한 범위에서 저장 또는 조회한 결과.

        Raises:
            ContextNotFound: 요청한 피어·발신자·대화가 지정된 소유 범위와 다른 경우.
        """
        delegation = await self.delegations.get(command.delegation_id)
        sender = await self.peers.get(command.sender_id)
        (await self.sessions.get(sender.session_id)).require_current_owner()
        task = await self.tasks.get(delegation.task_id)
        if delegation.sender_id != command.sender_id and task.owner_session_id != sender.session_id:
            raise ContextNotFound("Only the assigning peer can start this plan")
        source = await self.sources.get(delegation.source_id)
        originals = [source]
        while originals[-1].corrects_id is not None:
            originals.append(await self.sources.get(originals[-1].corrects_id))
        delegation.request_provider(
            task,
            f"""Delegation {delegation.uid}; role {delegation.role}; task {task.uid}; definition {delegation.definition_number}
Original source {source.uid}:
{"\n".join(f"Source {item.uid}: {item.body}" for item in reversed(originals))}
Required result: {task.definition.required_result}
Assigned scope: {delegation.scope}
Work only within this assignment. Report concrete evidence and remaining work.""",
        )
        return await self.delegations.save(delegation)

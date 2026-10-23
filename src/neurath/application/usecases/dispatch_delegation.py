"""배정과 원 지시를 같은 트랜잭션의 메시지로 연결하며 수락·실행 완료와 구분한다."""

from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.repositories.conversation import IConversationRepository
from neurath.application.ports.repositories.delegation import IDelegationRepository
from neurath.application.ports.repositories.message import IMessageRepository
from neurath.application.ports.repositories.peer import IPeerRepository
from neurath.application.ports.repositories.request_source import IRequestSourceRepository
from neurath.application.ports.repositories.session import ISessionRepository
from neurath.application.ports.repositories.task import ITaskRepository
from neurath.domain.aggregates.conversation import Conversation
from neurath.domain.aggregates.delegation import Delegation
from neurath.domain.aggregates.message import Message
from neurath.domain.errors import ContextNotFound, InvalidTaskState


@immutable
class DispatchDelegationCommand(AbstractCommand):
    """배정과 원 지시를 같은 트랜잭션의 메시지로 연결하며 수락·실행 완료와 구분한다.

    Attributes:
        delegation_id: 수락·보고할 원 배정 ID.
        sender_id: 배정 책임이 있는 발신 피어.
    """

    delegation_id: UUID
    sender_id: UUID


@UseCase()
class DispatchDelegationUseCase(IAsyncCommandUseCase[DispatchDelegationCommand, Delegation]):
    """배정과 원 지시를 같은 트랜잭션의 메시지로 연결하며 수락·실행 완료와 구분한다."""

    def __init__(
        self,
        delegations: IDelegationRepository,
        tasks: ITaskRepository,
        peers: IPeerRepository,
        conversations: IConversationRepository,
        messages: IMessageRepository,
        sources: IRequestSourceRepository,
        sessions: ISessionRepository,
    ) -> None:
        """요청 범위의 조회·저장 계약을 받는다.

        Args:
            delegations: Delegation aggregate의 범위 조회와 저장.
            tasks: Task aggregate의 범위 조회와 저장.
            peers: Peer aggregate의 범위 조회와 저장.
            conversations: Conversation aggregate의 범위 조회와 저장.
            messages: Message aggregate의 범위 조회와 저장.
            sources: 원래 사용자 지시와 최신 정정 원문.
            sessions: 배정 발신자의 실제 세션 소유 상태를 확인한다.
        """
        self.delegations = delegations
        self.sessions = sessions
        self.tasks = tasks
        self.peers = peers
        self.conversations = conversations
        self.messages = messages
        self.sources = sources

    @transactional
    @override
    async def run(self, command: DispatchDelegationCommand) -> Delegation:
        """배정과 원 지시를 같은 트랜잭션의 메시지로 연결하며 수락·실행 완료와 구분한다.

        Args:
            command: 원문·수신 범위와 해당 작업에 필요한 입력.

        Returns:
            Delegation: 요청한 범위에서 저장 또는 조회한 결과.

        Raises:
            ContextNotFound: 요청한 피어·발신자·대화가 지정된 소유 범위와 다른 경우.
            InvalidTaskState: 최신 배정·수신 경로·원문과 충돌하는 요청인 경우.
        """
        delegation = await self.delegations.get(command.delegation_id)
        sender = await self.peers.get(command.sender_id)
        (await self.sessions.get(sender.session_id)).require_current_owner()
        task = await self.tasks.get(delegation.task_id)
        if delegation.sender_id != command.sender_id and task.owner_session_id != sender.session_id:
            raise ContextNotFound("Only the assigning peer can dispatch this delegation")
        delegation.require_current(task)
        if delegation.message_id is not None:
            return delegation
        if delegation.recipient_id is None:
            raise InvalidTaskState("Observe the provider recipient before peer dispatch")
        await self.peers.get(delegation.recipient_id)
        source = await self.sources.get(delegation.source_id)
        originals = [source]
        while originals[-1].corrects_id is not None:
            originals.append(await self.sources.get(originals[-1].corrects_id))
        conversation = Conversation(
            uid=Conversation.next_id(), participants=(delegation.sender_id, delegation.recipient_id)
        )
        await self.conversations.save(conversation)
        message = Message(
            uid=Message.next_id(),
            conversation_id=conversation.uid,
            sender_id=delegation.sender_id,
            recipient_id=delegation.recipient_id,
            key=str(delegation.uid),
            title=task.definition.title,
            body=f"""Delegation: {delegation.uid}
Task: {task.uid} / definition {delegation.definition_number}
Role: {delegation.role}
Source: {source.uid}
{"\n".join(f"Source {item.uid}: {item.body}" for item in reversed(originals))}
Required result: {task.definition.required_result}
Assigned scope: {delegation.scope}
Accept the current assignment before execution; report evidence and remaining work to this assignment.""",
        )
        await self.messages.save(message)
        delegation.assign(message.uid)
        return await self.delegations.save(delegation)

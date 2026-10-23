"""정정·취소된 태스크의 배정에 중단 요청을 전파하고 실제 중단은 미확인으로 남긴다."""

from dataclasses import dataclass
from typing import override

from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.repositories.delegation import IDelegationRepository
from neurath.application.ports.repositories.message import IMessageRepository
from neurath.application.ports.repositories.task import ITaskRepository
from neurath.domain.aggregates.message import Message


@dataclass(frozen=True)
class ReconcileDelegationsCommand(AbstractCommand):
    """정정·취소된 태스크의 배정에 중단 요청을 전파하고 실제 중단은 미확인으로 남긴다.

    Attributes:
        task_id: 기존 요청에 연결된 작업.
    """

    task_id: str


@UseCase()
class ReconcileDelegationsUseCase(IAsyncCommandUseCase[ReconcileDelegationsCommand, None]):
    """정정·취소된 태스크의 배정에 중단 요청을 전파하고 실제 중단은 미확인으로 남긴다."""

    def __init__(
        self,
        tasks: ITaskRepository,
        delegations: IDelegationRepository,
        messages: IMessageRepository,
    ) -> None:
        """요청 범위의 조회·저장 계약을 받는다.

        Args:
            tasks: Task aggregate의 범위 조회와 저장.
            delegations: Delegation aggregate의 범위 조회와 저장.
            messages: Message aggregate의 범위 조회와 저장.
        """
        self.tasks = tasks
        self.delegations = delegations
        self.messages = messages

    @transactional
    @override
    async def run(self, command: ReconcileDelegationsCommand) -> None:
        """정정·취소된 태스크의 배정에 중단 요청을 전파하고 실제 중단은 미확인으로 남긴다.

        Args:
            command: 원문·수신 범위와 해당 작업에 필요한 입력.
        """
        task = await self.tasks.get(command.task_id)
        for delegation in await self.delegations.find_by_task_id(task.uid):
            before = delegation.stop_reason
            delegation.reconcile(task)
            if before == delegation.stop_reason:
                continue
            await self.delegations.save(delegation)
            if delegation.message_id is None or delegation.recipient_id is None:
                continue
            original = await self.messages.get(delegation.message_id)
            message = Message(
                uid=Message.next_id(),
                conversation_id=original.conversation_id,
                sender_id=delegation.sender_id,
                recipient_id=delegation.recipient_id,
                key=f"stop:{delegation.uid}",
                title="Assignment changed; stop old execution",
                body=f"Delegation {delegation.uid}: {delegation.stop_reason}. Read the latest task before any further work. Report actual stop evidence; cancellation is not yet confirmed.",
                reply_to=original.uid,
            )
            await self.messages.save(message)

"""호스트 응답 출력이 끝난 뒤 제출한 알림만 기록한다."""

from collections.abc import Sequence
from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.repositories.article import IArticleRepository
from neurath.application.ports.repositories.message import IMessageRepository
from neurath.application.ports.repositories.peer import IPeerRepository
from neurath.application.ports.repositories.task import ITaskRepository
from neurath.domain.aggregates.message import DeliveryStatus
from neurath.domain.values.task_monitor import NoticeStatus


@immutable
class RecordHookOutputCommand(AbstractCommand):
    """실제 stdout에 담긴 제목과 수신 피어의 정확한 식별자다.

    Attributes:
        peer_id: 호스트 사건에서 관찰한 수신 피어.
        messages: 출력한 메시지 식별자.
        articles: 출력한 기사와 개정 번호.
        monitors: 출력한 작업·감시·변화 사건의 정확한 순번.
    """

    peer_id: UUID
    messages: Sequence[UUID]
    articles: Sequence[tuple[UUID, int]]
    monitors: Sequence[tuple[UUID, int, int]] = ()


@UseCase()
class RecordHookOutputUseCase(IAsyncCommandUseCase[RecordHookOutputCommand, None]):
    """stdout 실패 시 호출되지 않으며 제출을 본문 읽음으로 바꾸지 않는다."""

    def __init__(
        self,
        peers: IPeerRepository,
        messages: IMessageRepository,
        articles: IArticleRepository,
        tasks: ITaskRepository,
    ) -> None:
        """실제 출력과 연결한 알림 저장 계약을 받는다.

        Args:
            peers: 관찰한 수신 피어.
            messages: 원 메시지와 제출 상태.
            articles: 제목 알림의 현재 개정.
            tasks: 실제 감시 사건의 제출 상태.
        """
        self.peers = peers
        self.messages = messages
        self.articles = articles
        self.tasks = tasks

    @transactional
    @override
    async def run(self, command: RecordHookOutputCommand) -> None:
        """아직 미제출인 정확한 메시지와 기사 개정만 제출 상태로 옮긴다.

        Args:
            command: 실제로 출력한 제목들의 원 ID.
        """
        peer = await self.peers.get(command.peer_id)
        for uid in command.messages:
            message = await self.messages.get(uid)
            message.require_recipient(peer.uid)
            if message.status is DeliveryStatus.PENDING:
                message.begin_delivery()
                await self.messages.save(message)
        for task_id, number, event_number in command.monitors:
            task = await self.tasks.get(task_id)
            task.require_scope(task.project_id, peer.session_id)
            monitor = task.monitor(number).begin_notice(event_number)
            event = monitor.event(event_number)
            monitor = monitor.notice_result(
                event_number, event.attempts, NoticeStatus.SUBMITTED, ""
            )
            task.update_monitor(monitor)
            await self.tasks.save(task)
        for uid, revision in command.articles:
            article = await self.articles.get(uid)
            if article.current.number != revision:
                continue
            article.consume_notices(peer, continuous=True)
            await self.articles.save(article)

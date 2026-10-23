"""신뢰하는 호출 어댑터가 전체 본문 출력을 마친 뒤 해당 개정의 열람만 기록한다."""

from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.repositories.article import IArticleRepository
from neurath.application.ports.repositories.peer import IPeerRepository
from neurath.application.ports.repositories.session import ISessionRepository
from neurath.application.ports.repositories.task import ITaskRepository
from neurath.domain.errors import RevisionConflict


@immutable
class RecordArticleReadCommand(AbstractCommand):
    """전체 출력한 개정과 그때 확인한 실제 작업 요구를 내부 어댑터가 전달한다.

    Attributes:
        peer_id: 전체 본문 출력을 마친 실제 피어.
        article_id: 실제 출력한 기사.
        revision_number: 실제 출력한 원문 개정.
        task_id: 원문을 실제 사용할 작업이며 단순 열람이면 None.
        expected_definition_number: 출력 전에 확인한 작업 요구 개정이며 없으면 None.
    """

    peer_id: UUID
    article_id: UUID
    revision_number: int
    task_id: UUID | None = None
    expected_definition_number: int | None = None


@UseCase()
class RecordArticleReadUseCase(IAsyncCommandUseCase[RecordArticleReadCommand, None]):
    """본문 출력 성공 뒤에만 호출되며 수동 seen CLI로 노출하지 않는다."""

    def __init__(
        self,
        articles: IArticleRepository,
        peers: IPeerRepository,
        sessions: ISessionRepository,
        tasks: ITaskRepository,
    ) -> None:
        """본문 출력과 작업 사용의 실제 범위를 다시 확인할 저장소를 받는다.

        Args:
            articles: 해당 개정 열람과 작업 사용을 저장한다.
            peers: 호출한 피어 주소를 확인한다.
            sessions: 호출자의 프로젝트를 확인한다.
            tasks: 실제 사용한 작업의 요구 개정을 대조한다.
        """
        self.articles = articles
        self.peers = peers
        self.sessions = sessions
        self.tasks = tasks

    @transactional
    @override
    async def run(self, command: RecordArticleReadCommand) -> None:
        """전체 출력한 개정에만 열람을 남기고 작업 요구가 바뀌면 잘못된 사용 연결을 거절한다.

        Args:
            command: 신뢰하는 어댑터가 출력한 개정과 실제 사용 작업.

        Raises:
            RevisionConflict: 출력 중 사용 작업의 요구 개정이 바뀐 경우.
        """
        peer = await self.peers.get(command.peer_id)
        session = await self.sessions.get(peer.session_id)
        article = await self.articles.get(command.article_id)
        article.require_project(session.project_id)
        article.read(peer.uid, command.revision_number)
        if command.task_id is not None:
            task = await self.tasks.get(command.task_id)
            task.require_project(session.project_id)
            if task.definition.number != command.expected_definition_number:
                raise RevisionConflict("Task changed while the article body was being delivered")
            article.use(peer.uid, command.revision_number, task.uid, task.definition.number)
        await self.articles.save(article)

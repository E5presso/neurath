"""지정한 소유 세션의 태스크 한 건과 보존된 이력을 조회한다."""

from collections.abc import Sequence
from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.query import AbstractQuery, IAsyncQueryUseCase
from spakky.plugins.sqlalchemy.persistency.session_manager import AsyncSessionManager
from sqlalchemy import select

from neurath.application.ports.repositories.delegation import IDelegationRepository
from neurath.application.ports.repositories.task import ITaskRepository
from neurath.domain.aggregates.delegation import Delegation
from neurath.domain.aggregates.task import Task
from neurath.infrastructure.models.article import ArticleModel, ArticleUseModel


@immutable
class GetTaskQuery(AbstractQuery):
    """소유 프로젝트·세션 안에서 상세 조회할 태스크를 지정한다.

    Attributes:
        project_id: 태스크와 참조 자료를 조회할 프로젝트 ID.
        session_id: 조회할 태스크의 소유 세션 ID.
        task_id: 현재 상태와 전체 이력을 조회할 태스크 ID.
    """

    project_id: UUID
    session_id: UUID
    task_id: UUID


@immutable
class TaskArticleImpact:
    """실제 사용한 기사 정정이 영향을 주는 작업 요구를 나타낸다.

    Attributes:
        article_id: 정정한 원 기사.
        peer_id: 옛 개정을 실제 사용한 피어.
        definition_number: 사용 당시 작업 요구 개정.
        used_revision: 실제 사용한 기사 개정.
        current_revision: 확인할 최신 기사 개정.
    """

    article_id: UUID
    peer_id: UUID
    definition_number: int
    used_revision: int
    current_revision: int


@immutable
class GetTaskResult:
    """조회한 태스크의 현재 상태와 전체 요구·시도·대기 이력을 반환한다.

    Attributes:
        task: 저장된 현재 요구와 모든 시도·대기 기록을 가진 태스크.
        delegations: 요구 개정·역할별 배정과 실제 보고. 옛 결과도 역사로 보존한다.
        article_impacts: 실제 사용한 옛 기사 개정의 미확인 정정 영향.
    """

    task: Task
    delegations: Sequence[Delegation] = ()
    article_impacts: Sequence[TaskArticleImpact] = ()


@UseCase()
class GetTaskUseCase(IAsyncQueryUseCase[GetTaskQuery, GetTaskResult]):
    """지정한 소유 세션의 태스크 한 건과 보존된 이력을 조회한다.

    프로젝트 또는 소유 세션이 다르면 ContextNotFound가 발생한다.
    조회는 작업 상태나 소유권을 변경하지 않는다.
    """

    def __init__(
        self,
        tasks: ITaskRepository,
        delegations: IDelegationRepository,
        sessions: AsyncSessionManager,
    ) -> None:
        """상세 조회할 태스크를 읽는 저장소를 받는다.

        Args:
            tasks: 태스크 ID로 현재 상태와 소유 이력을 조회한다.
            delegations: 태스크에 연결한 배정과 관찰을 조회한다.
            sessions: 실제 사용 기사와 해당 정정 영향을 조회한다.
        """
        self.tasks = tasks
        self.delegations = delegations
        self.sessions = sessions

    @transactional
    @override
    async def run(self, query: GetTaskQuery) -> GetTaskResult:
        """태스크의 소유 범위를 확인하고 현재 상태와 이력을 반환한다.

        Args:
            query: 조회할 태스크 ID와 그 태스크가 속해야 하는 프로젝트·소유 세션.

        Returns:
            GetTaskResult: 저장된 현재 요구와 모든 시도·대기 기록을 가진 태스크.
        """
        task = await self.tasks.get(query.task_id)
        task.require_scope(query.project_id, query.session_id)
        articles = await self.sessions.session.scalars(
            select(ArticleModel)
            .where(
                ArticleModel.id.in_(
                    select(ArticleUseModel.article_id).where(ArticleUseModel.task_id == task.uid)
                )
            )
            .order_by(ArticleModel.id)
        )
        impacts: list[TaskArticleImpact] = []
        for row in articles:
            article = row.to_domain()
            for peer_id in sorted({item.peer_id for item in article.uses}):
                impacts.extend(
                    TaskArticleImpact(
                        article_id=article.uid,
                        peer_id=peer_id,
                        definition_number=item.definition_number,
                        used_revision=item.revision_number,
                        current_revision=article.current.number,
                    )
                    for item in article.affected_tasks(peer_id)
                    if item.task_id == task.uid
                )
        return GetTaskResult(
            task=task,
            delegations=await self.delegations.find_by_task_id(task.uid),
            article_impacts=tuple(impacts),
        )

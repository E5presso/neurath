"""관련 범위의 과거 기록을 검색해 선택 조회할 식별자만 반환한다."""

from collections.abc import Sequence
from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.query import AbstractQuery, IAsyncQueryUseCase
from spakky.plugins.sqlalchemy.persistency.session_manager import AsyncSessionManager
from sqlalchemy import and_, func, or_, select

from neurath.domain.aggregates.memory import MemoryKind
from neurath.domain.errors import ContextNotFound
from neurath.domain.values.lesson_observation import LessonState
from neurath.infrastructure.models.memory import MemoryModel


@immutable
class SearchMemoryQuery(AbstractQuery):
    """기억 검색 범위와 본문 검색어를 지정한다.

    Attributes:
        project_id: 검색 대상 프로젝트.
        text: 부분 문자열이며 빈 값은 최근 기록 조회.
        session_id: 선택적인 기록 작성 세션.
        task_id: 선택적인 관련 작업.
        limit: 한 번에 조회할 1~100개 결과 수.
        after_id: 직전 페이지 마지막 기억이며 처음이면 None.
        kind: 필요한 기억 유형만 선택한다.
        lesson_state: 교훈의 마지막 적용·보류·철회 상태를 선택한다.
    """

    project_id: UUID
    text: str = ""
    session_id: UUID | None = None
    task_id: UUID | None = None
    limit: int = 20
    after_id: UUID | None = None
    kind: MemoryKind | None = None
    lesson_state: LessonState | None = None


@UseCase()
class SearchMemoryUseCase(IAsyncQueryUseCase[SearchMemoryQuery, Sequence[UUID]]):
    """명시한 프로젝트와 선택 범위의 기억 ID를 최신순으로 반환한다."""

    def __init__(self, session_manager: AsyncSessionManager) -> None:
        """검색 전용 SQLAlchemy 세션을 받는다.

        Args:
            session_manager: 현재 읽기 트랜잭션의 세션.
        """
        self.session_manager = session_manager

    @transactional
    @override
    async def run(self, query: SearchMemoryQuery) -> Sequence[UUID]:
        """과거 기록의 본문을 검색하되 현재 enclave에는 적용하지 않는다.

        Args:
            query: 검색 문자열·범위·개수.

        Returns:
            Sequence[UUID]: 선택 읽기에 사용할 기억 ID.

        Raises:
            ValueError: 결과 개수가 1~100 범위 밖인 경우.
            ContextNotFound: 커서가 선택한 프로젝트에 없는 경우.
        """
        if not 1 <= query.limit <= 100:
            raise ValueError("Search limit must be between 1 and 100")
        statement = select(MemoryModel.id).where(
            MemoryModel.project_id == query.project_id,
            MemoryModel.content.contains(query.text, autoescape=True),
        )
        if query.kind is not None:
            statement = statement.where(MemoryModel.kind == query.kind.value)
        if query.lesson_state is not None:
            statement = statement.where(
                MemoryModel.kind == MemoryKind.LESSON.value,
                func.json_extract(MemoryModel.lessons, "$[#-1].state") == query.lesson_state.value,
            )
        if query.session_id is not None:
            statement = statement.where(MemoryModel.session_id == query.session_id)
        if query.task_id is not None:
            statement = statement.where(MemoryModel.task_id == query.task_id)
        if query.after_id is not None:
            cursor = await self.session_manager.session.scalar(
                select(MemoryModel.created_at).where(
                    MemoryModel.project_id == query.project_id, MemoryModel.id == query.after_id
                )
            )
            if cursor is None:
                raise ContextNotFound("Memory cursor is outside the selected project")
            statement = statement.where(
                or_(
                    MemoryModel.created_at < cursor,
                    and_(MemoryModel.created_at == cursor, MemoryModel.id > query.after_id),
                )
            )
        rows = await self.session_manager.session.scalars(
            statement.order_by(MemoryModel.created_at.desc(), MemoryModel.id).limit(query.limit)
        )
        return tuple(rows)

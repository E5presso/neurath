"""체크포인트가 없어도 현재 원문·작업·절차·맥락을 소유권 변경 없이 미리 본다."""

from collections.abc import Sequence
from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.query import AbstractQuery, IAsyncQueryUseCase
from spakky.plugins.sqlalchemy.persistency.session_manager import AsyncSessionManager
from sqlalchemy import or_, select

from neurath.application.ports.repositories.session import ISessionRepository
from neurath.domain.aggregates.enclave import Enclave
from neurath.domain.aggregates.request_source import RequestSource
from neurath.domain.aggregates.session import HostSession
from neurath.domain.aggregates.task import Task
from neurath.domain.aggregates.workflow import WorkflowRun
from neurath.infrastructure.models.enclave import EnclaveModel
from neurath.infrastructure.models.memory import MemoryModel
from neurath.infrastructure.models.request_source import RequestSourceModel
from neurath.infrastructure.models.task import TaskModel
from neurath.infrastructure.models.workflow import WorkflowModel


@immutable
class PreviewSessionQuery(AbstractQuery):
    """명시적으로 미리 볼 원 작업의 세션 범위를 지정한다.

    Attributes:
        project_id: 관련 자료를 조회할 프로젝트.
        session_id: 소유권 변경 없이 읽을 세션.
    """

    project_id: UUID
    session_id: UUID


@immutable
class PreviewSessionResult:
    """과거 보고와 구분되는 현재 인수 후보의 실제 저장 상태다.

    Attributes:
        session: 예상 개정과 인수 연결을 가진 세션.
        sources: 현재 작업의 요구 출처 및 이 세션의 원문.
        tasks: 현재 소유 작업과 미완료 상태.
        workflows: 현재 작업의 정의·시도·검증 결과.
        enclaves: 현재 사실과 정정·삭제 이력.
        memory_ids: 상세 읽기로 선택할 과거 보고·자료 ID.
    """

    session: HostSession
    sources: Sequence[RequestSource]
    tasks: Sequence[Task]
    workflows: Sequence[WorkflowRun]
    enclaves: Sequence[Enclave]
    memory_ids: Sequence[UUID]


@UseCase()
class PreviewSessionUseCase(IAsyncQueryUseCase[PreviewSessionQuery, PreviewSessionResult]):
    """같은 트랜잭션의 현재 상태를 읽고 기억을 현재 사실로 덮어쓰지 않는다."""

    def __init__(self, sessions: ISessionRepository, session_manager: AsyncSessionManager) -> None:
        """범위 확인과 읽기 전용 투영에 필요한 의존성을 받는다.

        Args:
            sessions: 세션 범위와 개정 확인.
            session_manager: 현재 트랜잭션의 직접 조회 세션.
        """
        self.sessions = sessions
        self.session_manager = session_manager

    @transactional
    @override
    async def run(self, query: PreviewSessionQuery) -> PreviewSessionResult:
        """체크포인트 유무와 상관없이 현재 소유 작업을 조회한다.

        Args:
            query: 미리 볼 프로젝트·세션.

        Returns:
            PreviewSessionResult: 저장소 소유권과 상태를 바꾸지 않은 현재 자료.
        """
        session = await self.sessions.get(query.session_id)
        session.require_project(query.project_id)
        db = self.session_manager.session
        tasks = tuple(
            row.to_domain()
            for row in await db.scalars(
                select(TaskModel)
                .where(
                    TaskModel.project_id == query.project_id,
                    TaskModel.owner_session_id == query.session_id,
                )
                .order_by(TaskModel.created_at, TaskModel.id)
            )
        )
        source_ids = tuple(
            definition.source_id for task in tasks for definition in task.definitions
        )
        sources = tuple(
            row.to_domain()
            for row in await db.scalars(
                select(RequestSourceModel)
                .where(
                    RequestSourceModel.project_id == query.project_id,
                    or_(
                        RequestSourceModel.session_id == query.session_id,
                        RequestSourceModel.id.in_(source_ids),
                    ),
                )
                .order_by(RequestSourceModel.created_at, RequestSourceModel.id)
            )
        )
        workflows = tuple(
            row.to_domain()
            for row in await db.scalars(
                select(WorkflowModel)
                .where(
                    WorkflowModel.project_id == query.project_id,
                    WorkflowModel.session_id == query.session_id,
                )
                .order_by(WorkflowModel.id)
            )
        )
        enclaves = tuple(
            row.to_domain()
            for row in await db.scalars(
                select(EnclaveModel)
                .where(
                    EnclaveModel.project_id == query.project_id,
                    EnclaveModel.session_id == query.session_id,
                )
                .order_by(EnclaveModel.id)
            )
        )
        memories = tuple(
            await db.scalars(
                select(MemoryModel.id)
                .where(
                    MemoryModel.project_id == query.project_id,
                    MemoryModel.session_id == query.session_id,
                )
                .order_by(MemoryModel.created_at.desc(), MemoryModel.id)
            )
        )
        return PreviewSessionResult(
            session=session,
            sources=sources,
            tasks=tasks,
            workflows=workflows,
            enclaves=enclaves,
            memory_ids=memories,
        )

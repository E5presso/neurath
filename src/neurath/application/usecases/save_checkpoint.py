"""작업 완료 판정과 별개로 재개 가능한 보고를 저장한다."""

from collections.abc import Sequence
from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.repositories.memory import IMemoryRepository
from neurath.application.ports.repositories.session import ISessionRepository
from neurath.application.ports.repositories.task import ITaskRepository
from neurath.domain.aggregates.memory import Memory, MemoryKind


@immutable
class SaveCheckpointCommand(AbstractCommand):
    """현재 결과·판단·남은 일과 다음 행동을 보고로 전달한다.

    Attributes:
        project_id: 보고의 프로젝트.
        session_id: 보고를 남긴 세션.
        content: 원래 보고 본문.
        references: 보고의 출처·산출물 참조.
        task_id: 관련 작업 또는 None.
        graph_directory: 검증·저장 커밋 후 갱신할 선택적 Graphify 경로.
    """

    project_id: UUID
    session_id: UUID
    content: str
    references: Sequence[str]
    task_id: UUID | None = None
    graph_directory: str | None = None


@UseCase()
class SaveCheckpointUseCase(IAsyncCommandUseCase[SaveCheckpointCommand, Memory]):
    """보고를 검증·저장하고 선택적인 외부 갱신은 커밋 후 사건으로 요청한다."""

    def __init__(
        self, sessions: ISessionRepository, tasks: ITaskRepository, memories: IMemoryRepository
    ) -> None:
        """출처 범위와 보고 저장 계약을 받는다.

        Args:
            sessions: 세션 범위 확인.
            tasks: 선택한 작업 소유 확인.
            memories: 보고 저장.
        """
        self.sessions = sessions
        self.tasks = tasks
        self.memories = memories

    @transactional
    @override
    async def run(self, command: SaveCheckpointCommand) -> Memory:
        """원문을 보존한 체크포인트를 저장한다.

        Args:
            command: 보고 본문·참조·범위.

        Returns:
            Memory: 커밋할 보고의 스냅샷. 외부 갱신 결과는 저장된 기록을 다시 조회한다.
        """
        session = await self.sessions.get(command.session_id)
        session.require_project(command.project_id)
        session.require_current_owner()
        if command.task_id is not None:
            (await self.tasks.get(command.task_id)).require_scope(
                command.project_id, command.session_id
            )
        memory = Memory.create(
            command.project_id,
            command.session_id,
            command.task_id,
            MemoryKind.CHECKPOINT,
            command.content,
            command.references,
        )
        if command.graph_directory is not None:
            memory.request_graph_update(command.graph_directory)
        return await self.memories.save(memory)

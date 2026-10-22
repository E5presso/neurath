"""작업 완료 판정과 별개로 재개 가능한 보고를 저장한다."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import override

from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.repositories.memory import IMemoryRepository
from neurath.application.ports.repositories.session import ISessionRepository
from neurath.application.ports.repositories.task import ITaskRepository
from neurath.domain.aggregates.memory import Memory, MemoryKind


@dataclass(frozen=True)
class SaveCheckpointCommand(AbstractCommand):
    """현재 결과·판단·남은 일과 다음 행동을 보고로 전달한다.

    Attributes:
        project_id: 보고의 프로젝트.
        session_id: 보고를 남긴 세션.
        content: 원래 보고 본문.
        references: 보고의 출처·산출물 참조.
        task_id: 관련 작업 또는 None.
    """

    project_id: str
    session_id: str
    content: str
    references: Sequence[str]
    task_id: str | None = None


@UseCase()
class SaveCheckpointUseCase(IAsyncCommandUseCase[SaveCheckpointCommand, Memory]):
    """보고만 저장하며 가짜 태스크를 만들거나 미완료 작업을 닫지 않는다."""

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
            Memory: 상세 조회 가능한 체크포인트 기록.
        """
        session = await self.sessions.get(command.session_id)
        session.require_project(command.project_id)
        session.require_current_owner()
        if command.task_id is not None:
            (await self.tasks.get(command.task_id)).require_scope(
                command.project_id, command.session_id
            )
        return await self.memories.save(
            Memory.create(
                command.project_id,
                command.session_id,
                command.task_id,
                MemoryKind.CHECKPOINT,
                command.content,
                command.references,
            )
        )

"""관련 수행에서 교훈의 검증·적용·보류·철회 효과를 순서대로 보존한다."""

from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.repositories.memory import IMemoryRepository
from neurath.application.ports.repositories.session import ISessionRepository
from neurath.domain.aggregates.memory import Memory
from neurath.domain.errors import ContextNotFound
from neurath.domain.values.lesson_observation import LessonObservation


@immutable
class ObserveLessonCommand(AbstractCommand):
    """후속 관련 세션에서 관찰한 교훈의 실제 효과를 지정한다.

    Attributes:
        project_id: 교훈이 속한 프로젝트.
        session_id: 관찰을 기록할 현재 세션.
        memory_id: 출처가 보존된 교훈.
        observation: 검증·적용·보류·철회와 실제 효과 관찰.
    """

    project_id: UUID
    session_id: UUID
    memory_id: UUID
    observation: LessonObservation


@UseCase()
class ObserveLessonUseCase(IAsyncCommandUseCase[ObserveLessonCommand, Memory]):
    """원래 사용자 요청 범위의 교훈을 후속 세션에서 확인하고 악화 이력을 보존한다."""

    def __init__(self, memories: IMemoryRepository, sessions: ISessionRepository) -> None:
        """출처 있는 교훈과 현재 관찰 세션 조회 계약을 받는다.

        Args:
            memories: 교훈의 상태·효과 이력을 저장한다.
            sessions: 관찰 세션의 프로젝트와 현재 소유 상태를 확인한다.
        """
        self.memories = memories
        self.sessions = sessions

    @transactional
    @override
    async def run(self, command: ObserveLessonCommand) -> Memory:
        """권한 범위의 실제 관찰만 교훈 이력에 추가한다.

        Args:
            command: 교훈과 후속 효과의 실제 근거.

        Returns:
            Memory: 현재 상태와 이전 효과가 함께 남은 교훈.

        Raises:
            ContextNotFound: 관찰 세션·교훈의 프로젝트가 다른 경우.
        """
        session = await self.sessions.get(command.session_id)
        session.require_current_owner()
        memory = await self.memories.get(command.memory_id)
        if session.project_id != command.project_id or memory.project_id != command.project_id:
            raise ContextNotFound("Lesson belongs to another project")
        memory.observe_lesson(command.observation)
        return await self.memories.save(memory)

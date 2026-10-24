"""사용자가 요청하고 독립 평가한 회고에서만 지속 교훈 후보를 저장한다."""

from collections.abc import Sequence
from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.repositories.memory import IMemoryRepository
from neurath.application.ports.repositories.workflow import IWorkflowRepository
from neurath.application.ports.services.evaluation_context import (
    EvaluationContext,
    IEvaluationContextService,
)
from neurath.domain.aggregates.memory import Memory, MemoryKind
from neurath.domain.enums.reflection_choice import ReflectionChoice
from neurath.domain.errors import InvalidWorkflowState
from neurath.domain.values.evaluation_target import EvaluationKind
from neurath.domain.values.lesson_observation import LessonObservation, LessonState
from neurath.domain.values.phase_attempt import PhaseStatus


@immutable
class SaveLessonCommand(AbstractCommand):
    """요청된 회고와 관련된 개선 후보·적용 범위의 원문을 지정한다.

    Attributes:
        project_id: 회고 프로젝트.
        session_id: 회고 소유 세션.
        run_id: 실제 회고를 수행한 기존 실행.
        phase_key: 독립 회고 평가 단계.
        observed: 트랜잭션 밖에서 관찰한 현재 후보.
        run_version: 관찰한 실행 정의의 변경 토큰.
        content: 원인·개선 후보·적용 범위를 명시한 본문.
        references: 실제 사용자 요청·문제·검토의 근거.
    """

    project_id: UUID
    session_id: UUID
    run_id: UUID
    phase_key: str
    observed: EvaluationContext
    run_version: UUID
    content: str
    references: Sequence[str]


@UseCase()
class SaveLessonUseCase(IAsyncCommandUseCase[SaveLessonCommand, Memory]):
    """제안만으로 교훈을 만들지 않고 실제 요청과 평가를 확인한다."""

    def __init__(
        self,
        workflows: IWorkflowRepository,
        memories: IMemoryRepository,
        context: IEvaluationContextService,
    ) -> None:
        """회고 실행과 출처 있는 기억의 저장 계약을 받는다.

        Args:
            workflows: 회고 요청과 독립 보고를 조회한다.
            memories: 교훈 후보와 이력을 보존한다.
            context: 현재 회고 후보의 유효성을 대조한다.
        """
        self.workflows = workflows
        self.memories = memories
        self.context = context

    @transactional
    @override
    async def run(self, command: SaveLessonCommand) -> Memory:
        """수락된 독립 회고에 연결해 아직 적용하지 않은 교훈을 만든다.

        Args:
            command: 실제 회고 범위의 개선 후보와 근거.

        Returns:
            Memory: 조회 가능한 proposed 교훈과 원 회고 참조.

        Raises:
            InvalidWorkflowState: 외부 관찰 중 관련 원장이 바뀐 경우.
            ValueError: 사용자 요청 또는 현재 성공한 회고 평가가 없는 경우.
        """
        run = await self.workflows.get(command.run_id)
        run.require_scope(command.project_id, command.session_id)
        phase = run.evaluation_phase(command.phase_key)
        current = await self.context.load(run, phase)
        if run.version != command.run_version or current.candidate != command.observed.requirements:
            raise InvalidWorkflowState(
                "Evaluation metadata changed during external observation; read the current candidate"
            )
        attempt = run.latest(phase)
        if (
            run.reflection is not ReflectionChoice.REQUESTED
            or phase.evaluation is None
            or phase.evaluation.kind is not EvaluationKind.REFLECTION
            or attempt is None
            or attempt.status is not PhaseStatus.SUCCEEDED
        ):
            raise ValueError("Lessons require requested and independently evaluated reflection")
        if attempt.candidate != command.observed.candidate:
            raise ValueError("Reflection candidate changed before creating a lesson")
        memory = Memory.create(
            run.project_id,
            run.session_id,
            run.task_id,
            MemoryKind.LESSON,
            command.content,
            (*command.references, f"workflow:{run.uid}:{attempt.number}"),
        )
        memory.observe_lesson(
            LessonObservation(
                state=LessonState.PROPOSED,
                reason=run.reflection_context,
                references=memory.references,
            )
        )
        return await self.memories.save(memory)

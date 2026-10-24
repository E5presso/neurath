"""관찰 원문에 대한 에이전트의 용도 판단과 이번 턴의 제어권 반환을 연결한다."""

import json
from hashlib import sha256
from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.repositories.execution import IExecutionRepository
from neurath.application.ports.repositories.memory import IMemoryRepository
from neurath.application.ports.repositories.request_source import IRequestSourceRepository
from neurath.application.ports.repositories.task import ITaskRepository
from neurath.domain.aggregates.memory import Memory, MemoryKind
from neurath.domain.aggregates.request_source import SourceKind
from neurath.domain.enums.execution_pause_cause import ExecutionPauseCause
from neurath.serialization import encode_uuid


@immutable
class InterpretTurnCommand(AbstractCommand):
    """실제 현재 턴·원문과 그 내용을 읽은 판단을 지정한다.

    Attributes:
        project_id: 현재 관찰 프로젝트.
        session_id: 실제 관찰 세션.
        execution_id: 관찰된 루트 또는 자식 실행.
        turn_id: 현재 관찰 턴.
        kind: 원문의 요구 또는 상태·설명 용도.
        reason: 원문을 근거로 한 구체적인 판단 이유.
        pause: 이번 턴 종료를 허용하고 원 작업은 보존할지 여부.
        source_id: 현재 턴 원문 중 선택한 항목이며 None이면 마지막 원문.
    """

    project_id: UUID
    session_id: UUID
    execution_id: UUID
    turn_id: str
    kind: SourceKind
    reason: str
    pause: bool = False
    source_id: UUID | None = None


@immutable
class InterpretTurnResult:
    """원문 용도와 현재 제어 상태를 반환하며 작업 완료로 취급하지 않는다.

    Attributes:
        source_id: 본문을 그대로 유지한 원문.
        kind: 현재 해석된 원문 용도.
        memory_id: 원문·판단 이유·이전 용도의 기존 기억 기록.
        paused: 이번 턴 제어권 반환 여부.
    """

    source_id: UUID
    kind: SourceKind
    memory_id: UUID
    paused: bool


@UseCase()
class InterpretTurnUseCase(IAsyncCommandUseCase[InterpretTurnCommand, InterpretTurnResult]):
    """언어 분류기나 승인 기록 없이 기존 원문·실행·기억만 갱신한다."""

    def __init__(
        self,
        executions: IExecutionRepository,
        sources: IRequestSourceRepository,
        tasks: ITaskRepository,
        memories: IMemoryRepository,
    ) -> None:
        """현재 실행 범위와 원문·원 요구·판단 근거 저장소를 받는다.

        Args:
            executions: 현재 턴 제어 상태.
            sources: 원문을 보존하는 용도 정정.
            tasks: 이미 요구로 연결된 원문 보호.
            memories: 원문에 연결된 판단 근거와 이력.
        """
        self.executions = executions
        self.sources = sources
        self.tasks = tasks
        self.memories = memories

    @transactional
    @override
    async def run(self, command: InterpretTurnCommand) -> InterpretTurnResult:
        """현재 원문의 용도를 보존하고 선택한 제어 반환만 같은 트랜잭션에 반영한다.

        Args:
            command: 원문에 대한 에이전트의 실제 판단.

        Returns:
            InterpretTurnResult: 보존한 원문·판단과 현재 일시 중지 상태.

        Raises:
            ValueError: 판단 이유·현재 원문이 없거나 기존 요구를 배제하려는 경우.
        """
        if not command.reason.strip():
            raise ValueError("Explain the interpretation using the observed original source")
        execution = await self.executions.get(command.execution_id)
        execution.require_session(command.session_id)
        execution.require_turn(command.turn_id)
        originals = await self.sources.find_by_session_id(command.session_id)
        current = [
            source
            for source in originals
            if source.reference
            == f"host-event:{command.turn_id}:{sha256(source.body.encode()).hexdigest()}"
            and (command.source_id is None or source.uid == command.source_id)
        ]
        if not current:
            raise ValueError(
                "Select an original source observed in the current turn; no text was invented"
            )
        source = current[-1]
        source.require_project(command.project_id)
        tasks = await self.tasks.find_by_project_id(command.project_id)
        if command.kind is SourceKind.STATUS and any(
            definition.source_id == source.uid for task in tasks for definition in task.definitions
        ):
            raise ValueError("An existing task requirement cannot be excluded as status context")
        previous = source.kind
        source.interpret(command.kind)
        await self.sources.save(source)
        if command.pause:
            execution.pause(command.reason, ExecutionPauseCause.TURN_CONTROL)
            await self.executions.save(execution)
        memory = await self.memories.save(
            Memory.create(
                command.project_id,
                command.session_id,
                None,
                MemoryKind.ARTIFACT,
                json.dumps(
                    {
                        "source_id": source.uid,
                        "turn_id": command.turn_id,
                        "previous_kind": previous,
                        "kind": source.kind,
                        "reason": command.reason,
                        "pause_this_turn": command.pause,
                        "authority": "agent interpretation of preserved source; not a new instruction or task result",
                    },
                    default=encode_uuid,
                    ensure_ascii=False,
                ),
                (
                    f"source-interpretation:{source.uid}",
                    f"execution:{execution.uid}:{command.turn_id}",
                ),
            )
        )
        return InterpretTurnResult(
            source_id=source.uid,
            kind=source.kind,
            memory_id=memory.uid,
            paused=execution.pause_cause is ExecutionPauseCause.TURN_CONTROL,
        )

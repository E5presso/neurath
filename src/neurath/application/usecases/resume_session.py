"""실제 원 실행 종료를 확인한 뒤 현재 작업과 맥락의 소유 연결을 옮긴다."""

from typing import override
from uuid import UUID

from spakky.core.common.mutability import immutable
from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.repositories.enclave import IEnclaveRepository
from neurath.application.ports.repositories.execution import IExecutionRepository
from neurath.application.ports.repositories.memory import IMemoryRepository
from neurath.application.ports.repositories.session import ISessionRepository
from neurath.application.ports.repositories.task import ITaskRepository
from neurath.application.ports.repositories.workflow import IWorkflowRepository
from neurath.application.ports.repositories.writer import IWriterRepository
from neurath.domain.aggregates.memory import Memory, MemoryKind
from neurath.domain.aggregates.session import HostSession
from neurath.domain.errors import InvalidExecutionState, RevisionConflict


@immutable
class ResumeSessionCommand(AbstractCommand):
    """원 세션의 미리보기 개정과 실제 후속 세션을 지정한다.

    Attributes:
        project_id: 두 세션이 속해야 하는 프로젝트.
        source_session_id: 원 작업을 소유한 세션.
        target_session_id: 실제 작업을 이어갈 등록된 세션.
        expected_revision: 미리보기에서 읽은 원 세션 개정.
        turn_id: 후속 실행에서 관찰한 현재 턴.
    """

    project_id: UUID
    source_session_id: UUID
    target_session_id: UUID
    expected_revision: int
    turn_id: str


@UseCase()
class ResumeSessionUseCase(IAsyncCommandUseCase[ResumeSessionCommand, HostSession]):
    """체크포인트 유무와 무관하게 남은 작업·runner·enclave를 원자적으로 인수한다."""

    def __init__(
        self,
        sessions: ISessionRepository,
        executions: IExecutionRepository,
        writers: IWriterRepository,
        tasks: ITaskRepository,
        workflows: IWorkflowRepository,
        enclaves: IEnclaveRepository,
        memories: IMemoryRepository,
    ) -> None:
        """실제 실행·작성 상태와 인수할 aggregate 저장소를 받는다.

        Args:
            sessions: 인수 원본과 실제 후속 세션.
            executions: 원 실행 종료와 후속 턴 확인.
            writers: 아직 남아 있는 실제 작성 확인.
            tasks: 원 작업과 과거 시도 보존.
            workflows: 절차·시도·결과 보존.
            enclaves: 현재 맥락과 정정 이력 보존.
            memories: 실제 인수 내역 보고 저장.
        """
        self.sessions = sessions
        self.executions = executions
        self.writers = writers
        self.tasks = tasks
        self.workflows = workflows
        self.enclaves = enclaves
        self.memories = memories

    @transactional
    @override
    async def run(self, command: ResumeSessionCommand) -> HostSession:
        """원 실행의 중복 작성을 차단하고 후속 실행이 이어받을 현재 소유를 저장한다.

        Args:
            command: 명시적인 재개 또는 인수 대상과 관찰한 턴.

        Returns:
            HostSession: 현재 작업을 이어갈 실제 후속 세션.

        Raises:
            InvalidExecutionState: 후속 턴·원 실행 종료를 확인할 수 없거나 대상 맥락이 이미 있는 경우.
            RevisionConflict: 미리보기 이후 원 세션이 변경된 경우.
        """
        source = await self.sessions.get(command.source_session_id)
        target = await self.sessions.get(command.target_session_id)
        source.require_project(command.project_id)
        target.require_project(command.project_id)
        target.require_current_owner()
        target_execution = await self.executions.find_by_session_id_and_agent_id(target.uid, "")
        if target_execution is None:
            raise InvalidExecutionState("Target native execution has not been observed")
        target_execution.require_turn(command.turn_id)
        if source.revision != command.expected_revision:
            raise RevisionConflict("Source session changed")
        if source.uid == target.uid:
            target_execution.resume(command.turn_id)
            await self.executions.save(target_execution)
            return target
        originals = await self.executions.find_by_session_id(source.uid)
        if not originals:
            raise InvalidExecutionState("Source execution has not been observed")
        for execution in originals:
            execution.require_stopped()
            for writer in await self.writers.find_by_execution_id(execution.uid):
                writer.require_released()
        if await self.enclaves.find_by_session_id(target.uid):
            raise InvalidExecutionState(
                "Target enclave exists; read and reconcile it before handoff"
            )
        source.hand_off(target, command.expected_revision)
        for task in await self.tasks.find_by_project_id(command.project_id):
            if task.owner_session_id != source.uid:
                continue
            workflow = await self.workflows.find_by_task_id(task.uid)
            if workflow is not None:
                workflow.require_transferable()
                workflow.transfer(source.uid, target.uid)
                await self.workflows.save(workflow)
            task.transfer(source.uid, target.uid)
            await self.tasks.save(task)
        for enclave in await self.enclaves.find_by_session_id(source.uid):
            enclave.transfer(source.uid, target.uid)
            await self.enclaves.save(enclave)
        await self.sessions.save(source)
        target_execution.resume(command.turn_id)
        await self.executions.save(target_execution)
        await self.memories.save(
            Memory.create(
                command.project_id,
                source.uid,
                None,
                MemoryKind.HANDOFF,
                f"Session {source.uid} handed work to {target.uid}",
                (f"session:{source.uid}", f"session:{target.uid}"),
            )
        )
        return target

"""호스트 입력을 프로젝트·세션 범위에 연결해 현재 훅 처리 유스케이스에 전달한다."""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from typing import override

from spakky.core.stereotype.usecase import UseCase
from spakky.data.aspects.transactional import transactional
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.repositories.delegation import IDelegationRepository
from neurath.application.ports.repositories.enclave import IEnclaveRepository
from neurath.application.ports.repositories.execution import IExecutionRepository
from neurath.application.ports.repositories.message import IMessageRepository
from neurath.application.ports.repositories.peer import IPeerRepository
from neurath.application.ports.repositories.project import IProjectRepository
from neurath.application.ports.repositories.session import ISessionRepository
from neurath.application.ports.repositories.task import ITaskRepository
from neurath.application.ports.repositories.workflow import IWorkflowRepository
from neurath.application.ports.repositories.writer import IWriterRepository
from neurath.application.ports.services.directory_observer import IDirectoryObserverService
from neurath.domain.aggregates.delegation import Delegation
from neurath.domain.aggregates.enclave import Enclave
from neurath.domain.aggregates.execution import Execution
from neurath.domain.aggregates.message import DeliveryStatus
from neurath.domain.aggregates.peer import Peer
from neurath.domain.aggregates.project import Project
from neurath.domain.aggregates.session import HostSession
from neurath.domain.aggregates.task import Task
from neurath.domain.aggregates.workflow import WorkflowRun
from neurath.domain.aggregates.writer import Writer
from neurath.domain.errors import InvalidExecutionState, InvalidTaskState
from neurath.domain.runtime_records import ExecutionStatus, HookAction, HookEvent, Liveness
from neurath.domain.task_records import TaskStatus


@dataclass(frozen=True)
class ReceiveHookCommand(AbstractCommand):
    """CLI가 해석한 호스트 사건이며 내부 프로젝트·세션 ID는 유스케이스가 확인한다.

    Attributes:
        provider: 실제 사건을 전달한 호스트 공급자.
        host_session_id: 호스트가 준 네이티브 세션 ID.
        working_directory: 호스트가 준 작업 디렉터리.
        event: 관찰한 사건 이름.
        start_source: 시작·재개·포크·압축의 호스트 원인.
        turn_id: 실제 턴 또는 prompt ID.
        agent_id: 실제 네이티브 자식 ID.
        tool_use_id: 실제 도구 호출 ID.
        writes: 해당 도구가 작업 폴더에 쓰는 도구인지 여부.
        finished: 호스트 계약상 실제 종료가 확인됐는지 여부.
        interrupted: 실제 중단 여부.
        repeated: Stop 계속 수행 플래그.
        reason: 호스트가 전달한 실패·종료 사유.
        delegation_id: 이 실행이 맡은 배정이며 일반 호스트 작업이면 None.
    """

    provider: str
    host_session_id: str
    working_directory: str
    event: HookEvent
    start_source: str = ""
    turn_id: str = ""
    agent_id: str = ""
    tool_use_id: str = ""
    writes: bool = False
    finished: bool = False
    interrupted: bool = False
    repeated: bool = False
    reason: str = ""
    delegation_id: str | None = None


@dataclass(frozen=True)
class ReceiveHookResult:
    """CLI가 호스트 응답으로 표현할 제어와 안내만 반환한다.

    Attributes:
        action: 현재 실행에 대한 허용·계속·중지 판정.
        message: 호스트에 전달할 중지 사유와 TODO.
        restore: 현재 사건에서 맥락 복원을 요청하는지 여부.
        enclaves: 복원 범위의 최신 현재 맥락.
        tasks: 이 세션의 현재 요구와 원문 참조.
        workflows: 작업에 연결된 현재 절차와 시도.
        inbox: 이번 훅에 전달을 시도하는 메시지의 ID·제목 요약.

    """

    action: HookAction
    message: str
    restore: bool = False
    enclaves: Sequence[Enclave] = ()
    tasks: Sequence[Task] = ()
    workflows: Sequence[WorkflowRun] = ()
    inbox: Sequence[str] = ()


@UseCase()
class ReceiveHookUseCase(IAsyncCommandUseCase[ReceiveHookCommand, ReceiveHookResult]):
    """네이티브 세션을 확인하고 훅 사건의 상태 변경을 한 트랜잭션으로 반영한다."""

    def __init__(
        self,
        directories: IDirectoryObserverService,
        projects: IProjectRepository,
        sessions: ISessionRepository,
        executions: IExecutionRepository,
        writers: IWriterRepository,
        tasks: ITaskRepository,
        workflows: IWorkflowRepository,
        enclaves: IEnclaveRepository,
        peers: IPeerRepository,
        messages: IMessageRepository,
        delegations: IDelegationRepository,
    ) -> None:
        """위치 관찰과 훅 상태를 저장하는 의존성을 주입받는다.

        Args:
            directories: 첫 DB 접근 전에 작업 폴더를 관찰한다.
            projects: 관찰한 위치의 프로젝트를 저장한다.
            sessions: 네이티브 세션을 조회하고 등록한다.
            executions: 실제 턴과 중단 상태를 저장한다.
            writers: 작성 소유자와 세대를 저장한다.
            tasks: 해당 세션의 미완료 원장을 조회한다.
            workflows: 진행 중인 단계의 revision을 조회한다.
            enclaves: 압축·재개 시 현재 사실을 조회한다.
            peers: 실제 호스트 피어의 주소·활성 상태를 반영한다.
            messages: 수신할 메시지를 조회하고 제출 시도를 기록한다.
            delegations: 이 실행에 연결된 배정의 현재 요구를 확인한다.
        """
        self.directories = directories
        self.projects = projects
        self.sessions = sessions
        self.executions = executions
        self.writers = writers
        self.tasks = tasks
        self.workflows = workflows
        self.enclaves = enclaves
        self.peers = peers
        self.messages = messages
        self.delegations = delegations

    @transactional
    @override
    async def run(self, command: ReceiveHookCommand) -> ReceiveHookResult:
        """위치를 관찰한 뒤 세션 등록과 훅 변경을 원자적으로 저장한다.

        Args:
            command: 실제 호스트 신원과 정규화한 사건.

        Returns:
            ReceiveHookResult: 미완료 작업과 현재 상태에 따른 호스트 제어 응답.
        """
        observation = await asyncio.to_thread(self.directories.observe, command.working_directory)
        resource = ""
        if command.writes:
            resource = await asyncio.to_thread(
                self.directories.workspace, command.working_directory
            )
        candidates = Project.identify(observation)
        owners = []
        for location in candidates:
            owner = await self.projects.find_by_location(location)
            if owner is not None:
                owners.append(owner)
        project = Project.owner_of(owners)
        if project is None:
            project = Project.create(observation)
        project.associate(candidates)
        project = await self.projects.save(project)
        session = await self.sessions.find_by_project_id_and_provider_and_host_session_id(
            project.uid, command.provider, command.host_session_id
        )
        if session is None:
            session = await self.sessions.save(
                HostSession.create(
                    project.uid,
                    command.provider,
                    command.host_session_id,
                    observation.working_directory,
                )
            )
        if session.successor_id is not None:
            return ReceiveHookResult(
                HookAction.PAUSE, f"Work was handed off to session {session.successor_id}"
            )
        execution = await self.executions.find_by_session_id_and_agent_id(
            session.uid, command.agent_id
        )
        if execution is None:
            execution = await self.executions.save(Execution.create(session.uid, command.agent_id))
        peer = await self.peers.find_by_session_id_and_agent_id(session.uid, command.agent_id)
        if peer is None:
            peer = await self.peers.save(
                Peer(uid=Peer.next_id(), session_id=session.uid, agent_id=command.agent_id)
            )
        assignment: Delegation | None = None
        assignment_task: Task | None = None
        assignment_id = (
            command.delegation_id
            if command.delegation_id is not None
            else peer.current_delegation_id
        )
        if assignment_id is not None:
            assignment = await self.delegations.get(assignment_id)
            assignment_task = await self.tasks.get(assignment.task_id)
            if (
                command.delegation_id is not None
                and assignment.plan is not None
                and not command.agent_id
            ):
                assignment_task.require_project(project.uid)
                assignment.bind_provider_peer(command.provider, command.host_session_id, peer.uid)
                await self.delegations.save(assignment)
                peer.accept_assignment(assignment.uid)
                peer = await self.peers.save(peer)
            assignment.require_recipient(peer.uid)
            if command.event is HookEvent.PRE_TOOL_USE and command.writes:
                try:
                    assignment.require_current(assignment_task)
                except InvalidTaskState as error:
                    return ReceiveHookResult(HookAction.PAUSE, str(error))
        tasks = tuple(
            t
            for t in await self.tasks.find_by_project_id(project.uid)
            if t.owner_session_id == session.uid and not command.agent_id
        )
        if assignment is not None and assignment_task is not None and assignment.report is None:
            tasks = (
                (*tasks, assignment_task)
                if all(t.uid != assignment_task.uid for t in tasks)
                else tasks
            )
        todo = "\n".join(f"{t.uid}: {t.status.value} — {t.definition.title}" for t in tasks)
        try:
            action, _ = await self._apply(command, execution, tasks, resource)
        except InvalidExecutionState as error:
            return ReceiveHookResult(HookAction.PAUSE, f"{error}\n{todo}")
        execution = await self.executions.save(execution)
        peer.active = execution.status is ExecutionStatus.RUNNING
        await self.peers.save(peer)
        inbox: list[str] = []
        if peer.active and command.event in (
            HookEvent.SESSION_START,
            HookEvent.USER_PROMPT_SUBMIT,
            HookEvent.PRE_TOOL_USE,
        ):
            pending = [
                message
                for message in await self.messages.find_by_recipient_id(peer.uid)
                if message.status is DeliveryStatus.PENDING
            ][:20]
            for message in pending:
                message.begin_delivery()
                await self.messages.save(message)
                inbox.append(
                    f"Message {message.uid} from {message.sender_id}: {message.title}. Read the original body before ACK; this is not task acceptance."
                )
        restore = (
            command.event is HookEvent.SESSION_START
            and command.start_source in ("compact", "resume", "startup")
            and not command.agent_id
        )
        enclaves: Sequence[Enclave] = ()
        workflows: list[WorkflowRun] = []
        if restore:
            active = tuple(
                task
                for task in tasks
                if task.status not in (TaskStatus.SUCCEEDED, TaskStatus.INVALIDATED)
            )
            task_ids = {task.uid for task in active}
            enclaves = tuple(
                item
                for item in await self.enclaves.find_by_session_id(session.uid)
                if item.task_id is None or item.task_id in task_ids
            )
            for task in active:
                workflow = await self.workflows.find_by_task_id(task.uid)
                if workflow is not None:
                    workflows.append(workflow)
            tasks = active
        return ReceiveHookResult(
            action,
            f"{execution.reason}\n{todo}".strip(),
            restore,
            enclaves,
            tasks,
            workflows,
            inbox,
        )

    async def _apply(
        self,
        command: ReceiveHookCommand,
        execution: Execution,
        tasks: Sequence[Task],
        resource: str,
    ) -> tuple[HookAction, int | None]:
        """수명 사건과 도구 사건을 전달하며 현재 상태에서 거절된 도메인 예외를 전파한다.

        Args:
            command: 처리할 호스트 사건.
            execution: 현재 실행 aggregate.
            tasks: 해당 실행의 최신 태스크.
            resource: 실제 관찰한 작성 폴더.

        Returns:
            tuple[HookAction, int | None]: 호스트 제어와 선택적인 작성 세대.

        """
        if command.event in (HookEvent.SESSION_START, HookEvent.SUBAGENT_START):
            execution.observe_start(command.start_source)
            return HookAction.ALLOW, None
        if command.event == HookEvent.USER_PROMPT_SUBMIT:
            execution.begin_turn(command.turn_id)
            return HookAction.ALLOW, None
        if command.event == HookEvent.SESSION_END:
            execution.end(command.reason)
            return HookAction.ALLOW, None
        if not execution.turn_id and command.turn_id:
            execution.begin_turn(command.turn_id)
        if command.event == HookEvent.PRE_TOOL_USE and not resource:
            return HookAction.ALLOW, None
        execution.require_turn(command.turn_id)
        if command.event == HookEvent.INTERRUPT:
            execution.cancel(command.turn_id, command.reason or "Host interrupted execution")
            return HookAction.PAUSE, None
        if command.event == HookEvent.STOP_FAILURE:
            execution.pause(command.reason or "Host execution failed")
            return HookAction.PAUSE, None
        if command.event in (HookEvent.STOP, HookEvent.SUBAGENT_STOP):
            progress = []
            for task in tasks:
                workflow = await self.workflows.find_by_task_id(task.uid)
                if workflow is not None:
                    progress.append((workflow.uid, workflow.revision))
            return execution.decide_stop(tasks, repeated=command.repeated, progress=progress), None
        if command.event == HookEvent.PRE_TOOL_USE:
            if execution.status is not ExecutionStatus.RUNNING:
                return HookAction.PAUSE, None
            writer = await self.writers.find_by_resource(resource)
            if writer is None:
                writer = Writer.create(resource)
            generation = writer.acquire(execution.uid, command.turn_id, command.tool_use_id)
            (await self.writers.save(writer))
            return HookAction.ALLOW, generation
        await self._finish_write(command, execution, resource)
        if command.interrupted:
            execution.cancel(command.turn_id, command.reason or "Host interrupted execution")
        return HookAction.ALLOW, None

    async def _finish_write(
        self, command: ReceiveHookCommand, execution: Execution, resource: str
    ) -> None:
        """완료된 도구 사건이 가리키는 동일 작성 호출만 해제한다.

        Args:
            command: 종료 여부가 해석된 도구 사건.
            execution: 사건을 소유하는 현재 실행.
            resource: 실제 관찰한 작성 폴더.
        """
        if not resource or not command.finished:
            return
        writer = await self.writers.find_by_resource(resource)
        if writer is None:
            return
        if (writer.execution_id, writer.turn_id, writer.tool_use_id) != (
            execution.uid,
            command.turn_id,
            command.tool_use_id,
        ):
            return
        writer.release(execution.uid, writer.generation, Liveness.STOPPED)
        (await self.writers.save(writer))

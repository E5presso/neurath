"""네이티브 사건을 최신 실행·태스크·작성 상태에 적용하고 호스트 판정을 반환한다."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import override

from spakky.core.pod.annotations.pod import Pod
from spakky.core.stereotype.usecase import UseCase
from spakky.domain.application.command import AbstractCommand, IAsyncCommandUseCase

from neurath.application.ports.repositories.execution import IExecutionRepository
from neurath.application.ports.repositories.session import ISessionRepository
from neurath.application.ports.repositories.task import ITaskRepository
from neurath.application.ports.repositories.workflow import IWorkflowRepository
from neurath.application.ports.repositories.writer import IWriterRepository
from neurath.domain.aggregates.execution import Execution
from neurath.domain.aggregates.task import Task
from neurath.domain.aggregates.writer import Writer
from neurath.domain.errors import InvalidExecutionState
from neurath.domain.runtime_records import ExecutionStatus, HookAction, Liveness


@dataclass(frozen=True)
class HandleHookCommand(AbstractCommand):
    """호스트 어댑터가 실제 관찰한 사건과 작성 효과를 전달한다.

    Attributes:
        project_id: 등록된 프로젝트.
        session_id: 실제 네이티브 연결에 해당하는 내부 세션.
        event: 지원되는 호스트 사건 이름.
        start_source: SessionStart가 전달한 실제 시작 원인.
        turn_id: 실제 turn_id 또는 prompt_id이며 미제공 시 빈 문자열.
        agent_id: 네이티브 자식 식별자이며 루트는 빈 문자열.
        tool_use_id: 도구 사건의 실제 호출 ID.
        resource: 작성하는 정규 작업 폴더이며 읽기 호출은 빈 문자열.
        finished: 어댑터가 해당 작성 호출의 종료를 실제 확인했는지 여부.
        interrupted: 호스트가 보고한 실제 중단 여부.
        repeated: 호스트의 stop_hook_active 값.
        reason: 실패·중단에 대해 호스트가 전달한 설명.
    """

    project_id: str
    session_id: str
    event: str
    start_source: str = ""
    turn_id: str = ""
    agent_id: str = ""
    tool_use_id: str = ""
    resource: str = ""
    finished: bool = False
    interrupted: bool = False
    repeated: bool = False
    reason: str = ""


@dataclass(frozen=True)
class HandleHookResult:
    """호스트가 적용할 제어와 화면에 전달할 현재 TODO를 반환한다.

    Attributes:
        action: 허용·계속·중지 판정이며 작업 성공을 의미하지 않음.
        message: 중지 원인과 현재 TODO를 포함한 호스트 전달 본문.
        execution_id: 사건을 연결한 내부 실행 ID.
        generation: 이번 작성 취득의 세대이며 취득하지 않으면 None.
    """

    action: HookAction
    message: str
    execution_id: str
    generation: int | None = None


@UseCase(scope=Pod.Scope.CONTEXT)
class HandleHookUseCase(IAsyncCommandUseCase[HandleHookCommand, HandleHookResult]):
    """매 요청마다 최신 원장을 읽고 실제 사건에 해당하는 상태만 저장한다.

    SessionStart 재개는 취소를 자동으로 풀지 않는다. 새 UserPromptSubmit은 다음 턴을 기록하며 중지 해제는 명시적인 재개가 담당한다. 읽기에는 작성 임대를 요구하지 않으며 Stop으로 임대를 일괄 해제하지 않는다.
    호출자는 표준 쓰기 트랜잭션 안에서 실행하여 동시 취득을 직렬화한다.
    """

    def __init__(
        self,
        sessions: ISessionRepository,
        executions: IExecutionRepository,
        writers: IWriterRepository,
        tasks: ITaskRepository,
        workflows: IWorkflowRepository,
    ) -> None:
        """호스트 범위와 실행·임대·TODO를 읽을 저장소를 받는다.

        Args:
            sessions: 사건의 프로젝트 소속을 확인할 세션 저장소.
            executions: 루트와 네이티브 자식의 현재 실행 상태.
            writers: 작업 폴더별 실제 작성 소유자.
            tasks: 현재 프로젝트의 전체 태스크 원장.
            workflows: 태스크와 연결된 실제 단계 진행을 조회할 저장소.
        """
        self.sessions = sessions
        self.executions = executions
        self.writers = writers
        self.tasks = tasks
        self.workflows = workflows

    @override
    async def run(self, command: HandleHookCommand) -> HandleHookResult:
        """사건을 적용하고 이전 턴 사건은 현재 실행을 바꾸지 않고 중지 응답한다.

        Args:
            command: 네이티브 어댑터가 해석한 실제 사건.

        Returns:
            HandleHookResult: 최신 상태로 계산한 호스트 제어와 TODO 표시 내용.
        """
        (await self.sessions.get(command.session_id)).require_project(command.project_id)
        execution = await self.executions.find(command.session_id, command.agent_id)
        if execution is None:
            execution = Execution.create(command.session_id, command.agent_id)
            execution = await self.executions.save(execution)
        tasks = tuple(
            t
            for t in (await self.tasks.list(command.project_id))
            if t.owner_session_id == command.session_id and not command.agent_id
        )
        todo = "\n".join(f"{t.uid}: {t.status.value} — {t.definition.title}" for t in tasks)
        try:
            action, generation = await self._apply(command, execution, tasks)
        except InvalidExecutionState as error:
            return HandleHookResult(HookAction.PAUSE, f"{error}\n{todo}", execution.uid)
        execution = await self.executions.save(execution)
        message = f"{execution.reason}\n{todo}".strip()
        return HandleHookResult(action, message, execution.uid, generation)

    async def _apply(
        self, command: HandleHookCommand, execution: Execution, tasks: Sequence[Task]
    ) -> tuple[HookAction, int | None]:
        """수명 사건과 도구 사건을 해당 도메인 규칙에 전달한다.

        Args:
            command: 처리할 호스트 사건.
            execution: 현재 실행 aggregate.
            tasks: 해당 실행의 최신 태스크.

        Returns:
            tuple[HookAction, int | None]: 호스트 제어와 선택적인 작성 세대.

        Raises:
            InvalidExecutionState: 지원하지 않는 사건인 경우.
        """
        if command.event in ("SessionStart", "SubagentStart"):
            execution.observe_start(command.start_source)
            return HookAction.ALLOW, None
        if command.event == "UserPromptSubmit":
            execution.begin_turn(command.turn_id)
            return HookAction.ALLOW, None
        if command.event == "SessionEnd":
            execution.end(command.reason)
            return HookAction.ALLOW, None
        if not execution.turn_id and command.turn_id:
            execution.begin_turn(command.turn_id)
        if command.event == "PreToolUse" and not command.resource:
            return HookAction.ALLOW, None
        execution.require_turn(command.turn_id)
        if command.event == "Interrupt":
            execution.cancel(command.turn_id, command.reason or "Host interrupted execution")
            return HookAction.PAUSE, None
        if command.event == "StopFailure":
            execution.pause(command.reason or "Host execution failed")
            return HookAction.PAUSE, None
        if command.event in ("Stop", "SubagentStop"):
            progress = []
            for task in tasks:
                workflow = await self.workflows.find_by_task(task.uid)
                if workflow is not None:
                    progress.append((workflow.uid, workflow.revision))
            return execution.decide_stop(tasks, repeated=command.repeated, progress=progress), None
        if command.event == "PreToolUse":
            if execution.status is not ExecutionStatus.RUNNING:
                return HookAction.PAUSE, None
            writer = await self.writers.find(command.resource)
            if writer is None:
                writer = Writer.create(command.resource)
            generation = writer.acquire(execution.uid, command.turn_id, command.tool_use_id)
            (await self.writers.save(writer))
            return HookAction.ALLOW, generation
        if command.event in ("PostToolUse", "PostToolUseFailure"):
            (await self._finish_write(command, execution))
            if command.interrupted:
                execution.cancel(command.turn_id, command.reason or "Host interrupted execution")
            return HookAction.ALLOW, None
        raise InvalidExecutionState("Unsupported host event")

    async def _finish_write(self, command: HandleHookCommand, execution: Execution) -> None:
        """완료된 도구 사건이 가리키는 동일 작성 호출만 해제한다.

        Args:
            command: 종료 여부가 해석된 도구 사건.
            execution: 사건을 소유하는 현재 실행.
        """
        if not command.resource or not command.finished:
            return
        writer = await self.writers.find(command.resource)
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

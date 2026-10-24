"""네이티브 훅의 JSON 입출력을 spakky-typer 명령으로 제공한다."""

import asyncio
import json
import os
import re
import sys
from dataclasses import asdict, replace
from typing import Annotated, cast
from uuid import UUID

from spakky.plugins.sqlalchemy.persistency.connection_manager import AsyncConnectionManager
from spakky.plugins.typer.stereotypes.cli_controller import CliController, command
from typer import Exit, Option, echo

from neurath.application.usecases.poll_task_monitor import (
    PollTaskMonitorCommand,
    PollTaskMonitorUseCase,
)
from neurath.application.usecases.preserve_context_output import (
    PreserveContextOutputCommand,
    PreserveContextOutputUseCase,
)
from neurath.application.usecases.publish_host_environment import (
    PublishHostEnvironmentCommand,
    PublishHostEnvironmentUseCase,
)
from neurath.application.usecases.queue_transition_event import (
    QueueTransitionEventCommand,
    QueueTransitionEventUseCase,
)
from neurath.application.usecases.receive_hook import (
    ReceiveHookCommand,
    ReceiveHookResult,
    ReceiveHookUseCase,
)
from neurath.application.usecases.record_hook_output import (
    RecordHookOutputCommand,
    RecordHookOutputUseCase,
)
from neurath.application.usecases.record_recovery_failure import (
    RecordRecoveryFailureCommand,
    RecordRecoveryFailureUseCase,
)
from neurath.domain.enums.hook_action import HookAction
from neurath.domain.enums.hook_event import HookEvent
from neurath.domain.enums.provider_kind import ProviderKind
from neurath.domain.errors import RevisionConflict
from neurath.serialization import encode_uuid


@CliController("hook")
class HookCliController:
    """표준입력을 읽고 호스트 응답을 출력하며 호스트 입력은 주입된 유스케이스에 전달한다.

    도움말은 DB를 열지 않는다. 우회도 가능한 실제 턴 관찰은 유지하며 실패를 호스트 JSON으로 반환하여
    훅 장애가 같은 모델 턴을 계속 생성하지 않게 한다. 허용 결과는 네이티브 권한을 대체하지 않는다.
    """

    def __init__(
        self,
        usecase: ReceiveHookUseCase,
        transition: QueueTransitionEventUseCase,
        connection: AsyncConnectionManager,
        recovery: RecordRecoveryFailureUseCase,
        context_output: PreserveContextOutputUseCase,
        record_output: RecordHookOutputUseCase,
        environment: PublishHostEnvironmentUseCase,
        monitor: PollTaskMonitorUseCase,
    ) -> None:
        """스캔된 컨테이너에서 훅 수신 유스케이스를 직접 주입받는다.

        Args:
            usecase: 세션 등록·훅 적용·트랜잭션을 담당하는 유스케이스.
            transition: 실제 전환 중 사건의 내구성 보존.
            connection: 명령을 실행한 이벤트 루프에서 정리할 비동기 엔진.
            recovery: DB·출력 장애를 별도로 기록할 경로.
            context_output: 호스트 한도를 넘는 맥락을 보존할 경로.
            record_output: 실제 출력 이후에만 제출을 기록한다.
            environment: 공식 호스트 환경에 현재 주소를 전달한다.
            monitor: 같은 대화에 예약된 감시의 실제 변화만 조회한다.
        """
        self.usecase = usecase
        self.transition = transition
        self.connection = connection
        self.recovery = recovery
        self.context_output = context_output
        self.record_output = record_output
        self.environment = environment
        self.monitor = monitor

    @command("handle", help="표준입력의 네이티브 훅 JSON을 처리합니다.")
    async def handle(
        self,
        provider: Annotated[ProviderKind, Option("--provider", help="호스트 입력 규격")],
        bypass: Annotated[
            bool, Option("--bypass", help="차단만 우회하고 가능한 실제 턴 관찰은 보존")
        ] = False,
    ) -> None:
        """호스트 JSON 하나를 받아 제어 응답 하나를 표준출력에 기록한다.

        Args:
            provider: 설치된 훅의 공급자 규격.
            bypass: 관리 경로가 활성화한 우회이며 성공·승인을 기록하지 않음.

        Raises:
            Exit: 호스트 응답 출력이 실패해 정상 응답을 전달하지 못한 경우.
        """
        try:
            payload: dict[str, object] = {}
            submitted = None
            try:
                payload = self._read_payload()
                result, submitted = await self.dispatch(provider.value, payload, bypass=bypass)
            except Exception as error:
                receipt = await self.recovery.run(
                    RecordRecoveryFailureCommand(
                        detail=f"{type(error).__name__}: {error}; pending host event: {json.dumps(payload, ensure_ascii=False)}",
                        reference=f"hook:{provider.value}",
                    )
                )
                result = {
                    "continue": False,
                    "stopReason": f"Neurath hook failure: {error}. Use neurath maintenance diagnose; unfinished work is preserved. Recovery: {asdict(receipt)}",
                }
                if bypass or payload.get("hook_event_name") not in ("Stop", "SubagentStop"):
                    result = {
                        "systemMessage": f"Neurath bookkeeping failed and remains unverified; host tools remain available for recovery. Recovery: {asdict(receipt)}"
                    }
                if isinstance(payload.get("prompt"), str) and str(payload["prompt"]).startswith(
                    "NEURATH_MONITOR_TICK "
                ):
                    result = {
                        "continue": False,
                        "stopReason": f"Monitor callback could not be processed; stored work is preserved. Recovery: {asdict(receipt)}",
                    }
            try:
                echo(json.dumps(result, default=encode_uuid, ensure_ascii=False))
                if submitted is not None:
                    await self.record_output.run(submitted)
            except Exception as error:
                await self.recovery.run(
                    RecordRecoveryFailureCommand(
                        detail=f"Hook response output failed: {error}",
                        reference=f"hook:{provider.value}:stdout",
                    )
                )
                raise Exit(1) from error

        finally:
            await self.connection.dispose()

    @command("verify")
    async def verify(self, provider: Annotated[ProviderKind, Option("--provider")]) -> None:
        """복원 후 실제 Stop·작성 선행 훅의 차단 경로를 우회 없이 다시 실행한다.

        합성된 호스트 신원을 만들지 않는다. stdin은 호스트에서 확보한 실제 사건이어야 하며
        정상 허용은 차단 재검증 성공으로 표시하지 않는다. 실행 관찰은 일반 훅처럼 저장한다.

        Args:
            provider: 실제 사건을 관찰한 호스트 공급자.

        Raises:
            Exit: 차단을 관찰하지 못했거나 요청·DB 처리가 실패한 경우.
        """
        try:
            try:
                payload = self._read_payload()
                decoded = self.decode(provider.value, payload)
                self._require_guard_event(decoded.event)
                response, submitted = await self.dispatch(provider.value, payload)
                specific = response.get("hookSpecificOutput", {})
                verified = (
                    response.get("decision") == "block"
                    or response.get("continue") is False
                    or isinstance(specific, dict)
                    and specific.get("permissionDecision") == "deny"
                )
                echo(json.dumps({"verified": verified, "response": response}, default=encode_uuid))
                if submitted is not None:
                    await self.record_output.run(submitted)
            except Exception as error:
                await self.recovery.run(
                    RecordRecoveryFailureCommand(
                        detail=f"{type(error).__name__}: {error}", reference="hook:verify"
                    )
                )
                raise Exit(1) from error
            if not verified:
                raise Exit(1)
        finally:
            await self.connection.dispose()

    @staticmethod
    def _require_guard_event(event: HookEvent) -> None:
        """실제 차단을 검사할 수 있는 네이티브 사건만 선택한다.

        Args:
            event: 호스트 입력에서 해석한 사건.

        Raises:
            ValueError: Stop 또는 도구 선행 사건이 아닌 경우.
        """
        if event not in (HookEvent.STOP, HookEvent.SUBAGENT_STOP, HookEvent.PRE_TOOL_USE):
            raise ValueError("Verification requires a real Stop or PreToolUse event")

    @staticmethod
    def _read_payload() -> dict[str, object]:
        """표준입력의 JSON 객체를 읽고 호스트 사건이 아닌 값은 거절한다.

        Returns:
            dict[str, object]: 호스트가 전달한 JSON 객체.

        Raises:
            ValueError: JSON이 잘못됐거나 최상위 값이 객체가 아닌 경우.
        """
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise ValueError("Hook input must be a JSON object")
        return cast(dict[str, object], payload)

    async def dispatch(
        self, provider: str, payload: dict[str, object], *, bypass: bool = False
    ) -> tuple[dict[str, object], RecordHookOutputCommand | None]:
        """해석한 입력으로 요청을 열고 코어 결과를 호스트 응답 형식으로 변환한다.

        Args:
            provider: 실제 호스트 공급자.
            payload: 호스트가 전달한 JSON 객체.
            bypass: 실제 관찰은 기록하되 하네스 차단만 해제한다.

        Returns:
            tuple[dict[str, object], RecordHookOutputCommand | None]: 호스트 응답과 출력 후 제출 기록.
        """
        command = replace(self.decode(provider, payload), bypass=bypass)
        queued = await self.transition.run(
            QueueTransitionEventCommand(hook=command, payload=payload)
        )
        if queued is not None:
            message = f"Neurath store transition: event {queued} is durably queued. Work completion and host response delivery remain unverified; ordinary host tools remain available for compatible recovery and migration replay."
            if command.event in (HookEvent.STOP, HookEvent.SUBAGENT_STOP):
                return {
                    "systemMessage": f"{message} Harness enforcement is suspended for this stop: return control to the user without another recovery turn. Pending work and events remain unfinished; this is not task completion."
                }, None
            if command.prompt.startswith("NEURATH_MONITOR_TICK "):
                return {"continue": False, "stopReason": message}, None
            return {"systemMessage": message}, None
        callback = re.fullmatch(
            r"NEURATH_MONITOR_TICK ([0-9a-fA-F-]{36}) ([1-9][0-9]*)", command.prompt.strip()
        )
        if command.event is HookEvent.USER_PROMPT_SUBMIT and callback is not None:
            return await self._monitor_callback(command, UUID(callback[1]), int(callback[2]))
        result = await self._receive(command)
        if command.event is HookEvent.SESSION_START:
            await self.environment.run(
                PublishHostEnvironmentCommand(provider=provider, session=command.host_session_id)
            )
        response: dict[str, object] = {}
        if bypass:
            response["systemMessage"] = (
                "Neurath hook bypass is enabled; enforcement only is suspended, task outcomes and host permissions are unchanged"
            )
        elif result.action is HookAction.PAUSE:
            return {"continue": False, "stopReason": result.message or "Execution is paused"}, None
        elif result.action is HookAction.CONTINUE:
            if command.event is HookEvent.PRE_TOOL_USE:
                return {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": result.message,
                    }
                }, None
            return {
                "decision": "block",
                "reason": "Continue unfinished work:\n" + result.message,
            }, None
        if result.restore or result.inbox:
            context = self._context(result)
            if context:
                response["hookSpecificOutput"] = {
                    "hookEventName": command.event.value,
                    "additionalContext": await self.context_output.run(
                        PreserveContextOutputCommand(content=context)
                    ),
                }
        receipt = None
        if result.peer_id is not None and (result.message_ids or result.article_ids):
            receipt = RecordHookOutputCommand(
                peer_id=result.peer_id, messages=result.message_ids, articles=result.article_ids
            )
        return response, receipt

    async def _receive(self, command: ReceiveHookCommand) -> ReceiveHookResult:
        """롤백된 훅 DB 경합만 짧게 재조회하여 실제 작성 충돌을 판단한다.

        Args:
            command: 같은 네이티브 사건.

        Returns:
            ReceiveHookResult: 새 원장 상태에 근거한 실제 제어 결과.
        """
        for attempt in range(2):
            try:
                return await self.usecase.run(command)
            except RevisionConflict:
                await asyncio.sleep(0.02 * (attempt + 1))
        return await self.usecase.run(command)

    async def _monitor_callback(
        self, command: ReceiveHookCommand, task_id: UUID, number: int
    ) -> tuple[dict[str, object], RecordHookOutputCommand | None]:
        """등록된 감시의 변화만 원 대화에 전달하며 같은 상태는 모델 실행 전에 끝낸다.

        Args:
            command: 실제 호스트 콜백 주소.
            task_id: 등록된 원 작업.
            number: 원 감시 순번.

        Returns:
            tuple[dict[str, object], RecordHookOutputCommand | None]: 호스트 응답과 출력 이후 기록.
        """
        result = await self.monitor.run(
            PollTaskMonitorCommand(
                task_id=task_id,
                monitor_number=number,
                session=command.host_session_id,
                directory=command.working_directory,
                provider=command.provider,
            )
        )
        if not result.events and not result.attention:
            return {
                "continue": False,
                "stopReason": "No new monitored event; no model work is needed.",
            }, None
        await self._receive(replace(command, prompt=""))
        lines = [
            f"Existing requested monitor for task {task_id}. This callback is not a new user goal."
        ]
        lines.extend(
            f"Event {event.number}: {event.body}\nObserved: {event.state}\nEvidence: {event.reference}"
            for event in result.events
        )
        if result.attention:
            lines.append(result.attention)
        lines.append(
            "Inspect the actual change, continue only the original requested scope, and stop the host schedule when the wait ends or its budget is exhausted."
        )
        return {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": await self.context_output.run(
                    PreserveContextOutputCommand(content="\n".join(lines))
                ),
            }
        }, RecordHookOutputCommand(
            peer_id=result.peer_id,
            messages=(),
            articles=(),
            monitors=tuple((task_id, number, event.number) for event in result.events),
        )

    @staticmethod
    def _context(result: ReceiveHookResult) -> str:
        """현재 저장 상태를 호스트가 다음 모델 입력에 전달할 짧은 맥락으로 표현한다.

        Args:
            result: 현재 범위의 사실·요구·절차.

        Returns:
            str: 과거·삭제된 사실을 제외한 맥락이며 빈 상태는 빈 문자열.

        """
        lines: list[str] = list(result.inbox)
        for enclave in result.enclaves:
            for fact in enclave.facts:
                lines.append(
                    f"[{fact.kind.value}] {fact.key}: {fact.value} (sources: {', '.join(fact.references)})"
                )
        for lesson in result.lessons:
            lines.append(
                f"Previously applied project improvement (current instructions take precedence): {lesson.content}; memory:{lesson.uid}"
            )
        for task in result.tasks:
            lines.append(
                f"Task {task.uid} [{task.status.value}]: {task.definition.title}; required: {task.definition.required_result}; source: {task.definition.source_id}"
            )
        for run in result.workflows:
            phase = run.current
            lines.append(
                f"Workflow {run.uid} revision {run.revision}: {run.definition.skill}; next: {phase.key if phase is not None else 'none'}; attempts: {len(run.attempts)}"
            )
        if not lines:
            return ""
        context = "Neurath current stored context (not new user instructions):\n" + "\n".join(lines)
        return context

    @classmethod
    def decode(cls, provider: str, payload: dict[str, object]) -> ReceiveHookCommand:
        """공급자별 턴·도구 종료 계약을 정규화하고 누락된 신원을 꾸며 만들지 않는다.

        Args:
            provider: 호스트 공급자 이름.
            payload: 실제 호스트의 사건 JSON 객체.

        Returns:
            ReceiveHookCommand: 실제 호스트 식별자와 정규화된 사건.

        Raises:
            ValueError: 필수 식별자나 부울 필드의 형식이 잘못된 경우.
        """
        event = HookEvent(cls._text(payload, "hook_event_name", required=True))
        session = cls._text(payload, "session_id", required=True)
        directory = cls._text(payload, "cwd", required=True)
        turn = cls._text(payload, "turn_id" if provider == "codex" else "prompt_id")
        tool = cls._text(payload, "tool_name")
        agent = cls._text(payload, "agent_id")
        call = cls._text(payload, "tool_use_id")
        repeated = payload.get("stop_hook_active", False)
        interrupted = payload.get("is_interrupt", False)
        response = payload.get("tool_response")
        if provider == "claude" and tool == "Bash" and isinstance(response, dict):
            interrupted = response.get("interrupted", interrupted)
        if not isinstance(repeated, bool) or not isinstance(interrupted, bool):
            raise ValueError("Hook flags must be booleans")
        writes = False
        tool_input = payload.get("tool_input")
        write_target = tool_input.get("file_path", "") if isinstance(tool_input, dict) else ""
        if not isinstance(write_target, str):
            write_target = ""
        if event in (
            HookEvent.PRE_TOOL_USE,
            HookEvent.POST_TOOL_USE,
            HookEvent.POST_TOOL_USE_FAILURE,
        ):
            if not tool or not call:
                raise ValueError("Tool event requires a tool name and call ID")
            writes = tool in {"Edit", "Write", "apply_patch"}
        return ReceiveHookCommand(
            delegation_id=UUID(value)
            if (value := os.environ.get("NEURATH_DELEGATION_ID"))
            else None,
            provider=provider,
            prompt=cls._text(payload, "prompt"),
            host_session_id=session,
            working_directory=directory,
            event=event,
            start_source=cls._text(payload, "source"),
            turn_id=turn,
            agent_id=agent,
            tool_use_id=call,
            writes=writes,
            write_target=write_target,
            write_targets=cls._patch_targets(tool_input) if tool == "apply_patch" else (),
            repeated=repeated,
            interrupted=interrupted,
            reason=cls._text(payload, "error") or cls._text(payload, "reason"),
            finished=cls._finished(provider, payload, event, tool),
        )

    @staticmethod
    def _patch_targets(tool_input: object) -> tuple[str, ...]:
        """네이티브 apply_patch 형식의 파일 헤더만 읽고 셸 명령은 해석하지 않는다.

        Args:
            tool_input: 호스트가 전달한 패치 문자열 또는 command 객체.

        Returns:
            tuple[str, ...]: 실제 패치 헤더의 중복 없는 파일 경로.
        """
        content = tool_input.get("command", "") if isinstance(tool_input, dict) else tool_input
        if not isinstance(content, str):
            return ()
        targets: list[str] = []
        for line in content.splitlines():
            for prefix in (
                "*** Add File: ",
                "*** Update File: ",
                "*** Delete File: ",
                "*** Move to: ",
            ):
                if line.startswith(prefix):
                    target = line.removeprefix(prefix).strip()
                    if target and target not in targets:
                        targets.append(target)
                    break
        return tuple(targets)

    @staticmethod
    def _finished(provider: str, payload: dict[str, object], event: HookEvent, tool: str) -> bool:
        """동기 도구 결과와 종료 코드가 확인된 셸 결과만 작성 종료로 판정한다.

        Args:
            provider: 공급자별 종료 계약을 선택할 호스트 이름.
            payload: 호스트 결과를 포함한 사건.
            event: 실제 사건 이름.
            tool: 네이티브 도구 이름.

        Returns:
            bool: 백그라운드·유실·알 수 없는 도구는 False이며 임대를 보존함.
        """
        if event == HookEvent.POST_TOOL_USE_FAILURE:
            return tool in ("Edit", "Write", "apply_patch")
        if event != HookEvent.POST_TOOL_USE:
            return False
        if tool in ("Edit", "Write", "apply_patch"):
            return True
        response = payload.get("tool_response")
        if provider == "codex" and tool == "Bash" and isinstance(response, str):
            return True
        if not isinstance(response, dict):
            return False
        response = cast(dict[str, object], response)
        if response.get("session_id") is not None or response.get("backgroundTaskId") is not None:
            return False
        if provider == "claude" and tool == "Bash":
            return (
                isinstance(response.get("stdout"), str)
                and isinstance(response.get("stderr"), str)
                and isinstance(response.get("interrupted"), bool)
            )
        return type(response.get("exit_code")) is int

    @staticmethod
    def _text(payload: dict[str, object], key: str, *, required: bool = False) -> str:
        """선택 문자열의 부재와 잘못된 형식을 구분한다.

        Args:
            payload: 네이티브 입력 객체.
            key: 읽을 필드 이름.
            required: 비어 있지 않은 문자열을 요구할지 여부.

        Returns:
            str: 실제 입력 문자열이며 선택 필드가 없으면 빈 문자열.

        Raises:
            ValueError: 문자열 형식이 아니거나 필수 문자열이 비어 있는 경우.
        """
        value = payload.get(key, "")
        if not isinstance(value, str) or (required and not value.strip()):
            raise ValueError(f"Invalid hook field: {key}")
        return value

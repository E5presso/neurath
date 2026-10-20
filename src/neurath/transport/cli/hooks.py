"""네이티브 훅의 JSON 입출력을 spakky-typer 명령으로 제공한다."""

import json
import sys
from enum import StrEnum
from typing import Annotated, cast

from spakky.core.pod.annotations.pod import Pod
from spakky.plugins.typer.stereotypes.cli_controller import CliController, command
from typer import Option, echo

from neurath.application.usecases.receive_hook import ReceiveHookCommand, ReceiveHookUseCase
from neurath.domain.runtime_records import HookAction


class HookProvider(StrEnum):
    """설치된 훅이 지정하는 네이티브 입력 규격이다.

    Attributes:
        CODEX: Codex의 turn_id와 도구 사건 규격.
        CLAUDE: Claude의 prompt_id와 도구 사건 규격.
    """

    CODEX = "codex"
    CLAUDE = "claude"


@CliController("hook", scope=Pod.Scope.CONTEXT)
class HookCliController:
    """표준입력을 읽고 호스트 응답을 출력하며 호스트 입력은 주입된 유스케이스에 전달한다.

    도움말과 우회는 유스케이스나 DB 트랜잭션을 실행하지 않는다. 실패도 호스트가 해석하는 JSON으로 반환하여
    훅 장애가 같은 모델 턴을 계속 생성하지 않게 한다. 허용 결과는 네이티브 권한을 대체하지 않는다.
    """

    def __init__(self, usecase: ReceiveHookUseCase) -> None:
        """스캔된 컨테이너에서 훅 수신 유스케이스를 직접 주입받는다.

        Args:
            usecase: 세션 등록·훅 적용·트랜잭션을 담당하는 유스케이스.
        """
        self.usecase = usecase

    @command("handle", help="표준입력의 네이티브 훅 JSON을 처리합니다.")
    async def handle(
        self,
        provider: Annotated[HookProvider, Option("--provider", help="호스트 입력 규격")],
        bypass: Annotated[bool, Option("--bypass", help="원장을 변경하지 않고 훅을 우회")] = False,
    ) -> None:
        """호스트 JSON 하나를 받아 제어 응답 하나를 표준출력에 기록한다.

        Args:
            provider: 설치된 훅의 공급자 규격.
            bypass: 관리 경로가 활성화한 우회이며 성공·승인을 기록하지 않음.
        """
        if bypass:
            echo(
                json.dumps(
                    {"systemMessage": "Neurath hook bypass is enabled; task state is unchanged"}
                )
            )
            return
        try:
            result = await self.dispatch(provider.value, self._read_payload())
        except Exception as error:
            result = {
                "continue": False,
                "stopReason": f"Neurath hook failure: {error}. Use the management recovery/bypass path; unfinished work is preserved.",
            }
        echo(json.dumps(result, ensure_ascii=False))

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

    async def dispatch(self, provider: str, payload: dict[str, object]) -> dict[str, object]:
        """해석한 입력으로 요청을 열고 코어 결과를 호스트 응답 형식으로 변환한다.

        Args:
            provider: 실제 호스트 공급자.
            payload: 호스트가 전달한 JSON 객체.

        Returns:
            dict[str, object]: 네이티브 허용·계속·중지 응답.
        """
        command = self.decode(provider, payload)
        result = await self.usecase.run(command)
        if result.action is HookAction.PAUSE:
            return {"continue": False, "stopReason": result.message or "Execution is paused"}
        if result.action is HookAction.CONTINUE:
            return {"decision": "block", "reason": "Continue unfinished work:\n" + result.message}
        return {}

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
        event = cls._text(payload, "hook_event_name", required=True)
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
        if event in ("PreToolUse", "PostToolUse", "PostToolUseFailure"):
            if not tool or not call:
                raise ValueError("Tool event requires a tool name and call ID")
            writes = tool in {"Edit", "Write", "Bash", "apply_patch", "exec_command"}
        return ReceiveHookCommand(
            provider=provider,
            host_session_id=session,
            working_directory=directory,
            event=event,
            start_source=cls._text(payload, "source"),
            turn_id=turn,
            agent_id=agent,
            tool_use_id=call,
            writes=writes,
            repeated=repeated,
            interrupted=interrupted,
            reason=cls._text(payload, "error") or cls._text(payload, "reason"),
            finished=cls._finished(provider, payload, event, tool),
        )

    @staticmethod
    def _finished(provider: str, payload: dict[str, object], event: str, tool: str) -> bool:
        """동기 도구 결과와 종료 코드가 확인된 셸 결과만 작성 종료로 판정한다.

        Args:
            provider: 공급자별 종료 계약을 선택할 호스트 이름.
            payload: 호스트 결과를 포함한 사건.
            event: 실제 사건 이름.
            tool: 네이티브 도구 이름.

        Returns:
            bool: 백그라운드·유실·알 수 없는 도구는 False이며 임대를 보존함.
        """
        if event == "PostToolUseFailure":
            return tool in ("Edit", "Write", "apply_patch")
        if event != "PostToolUse":
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

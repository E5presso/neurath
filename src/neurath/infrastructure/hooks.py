"""Codex·Claude의 공식 훅 입력과 제어 JSON을 요청별 코어 호출에 연결한다."""

import os
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import cast

from spakky.plugins.sqlalchemy.persistency.transaction import Transaction

from neurath.application.usecases.handle_hook import HandleHookCommand, HandleHookUseCase
from neurath.application.usecases.register_session import (
    RegisterSessionCommand,
    RegisterSessionUseCase,
)
from neurath.domain.runtime_records import HookAction
from neurath.infrastructure.directory_observer import GitDirectoryObserverService
from neurath.infrastructure.providers import DatabaseSettings, request_container


class NativeHookAdapter:
    """실제 호스트 사건만 해석하고 실패 시 모델 재시도 대신 제어권을 반환한다.

    허용 응답에는 네이티브 permissionDecision=allow를 쓰지 않는다. Neurath의
    판정은 호스트 권한을 대신하지 않는다. write_tools는 설치 어댑터가 확인한 작업 폴더 작성 도구 목록이다.
    셸 문자열을 읽기 전용이라고 추측하거나 모든 외부 도구를 작성으로 분류하지 않는다.
    """

    def __init__(
        self,
        provider: str,
        database: Path,
        write_tools: frozenset[str] = frozenset(
            {"Edit", "Write", "Bash", "apply_patch", "exec_command"}
        ),
    ) -> None:
        """호스트 공급자·사용자 DB·확인된 작성 도구 목록을 지정한다.

        Args:
            provider: codex 또는 claude 공급자.
            database: 초기화된 사용자 단위 SQLite 경로.
            write_tools: 네이티브 도구 정의에서 확인한 작업 폴더 작성 도구 이름.

        Raises:
            ValueError: 지원하지 않는 호스트 공급자인 경우.
        """
        if provider not in ("codex", "claude"):
            raise ValueError("Unsupported hook provider")
        self.provider = provider
        self.database = database
        self.write_tools = write_tools

    def handle(self, payload: dict[str, object], *, bypass: bool = False) -> dict[str, object]:
        """실제 사건을 처리하고 호스트가 해석하는 허용·계속·중지 JSON을 반환한다.

        DB·어댑터 장애는 continue:false와 사용자 표시 사유로 반환한다. 우회는 별도
        관리 경로가 넘기는 설치 설정이며 DB가 손상돼도 읽힌다. 우회가 성공·인간 승인·
        읽음 확인을 기록하거나 원장을 변경하지 않는다.

        Args:
            payload: 호스트가 표준입력으로 보낸 JSON 객체.
            bypass: 관리 경로에서 활성화한 공식 훅 우회 설정.

        Returns:
            dict[str, object]: 호스트 출력 계약에 맞는 제어 JSON.
        """
        if bypass:
            return {"systemMessage": "Neurath hook bypass is enabled; task state is unchanged"}
        try:
            command, directory, native_session = self.decode(payload)
            observation = GitDirectoryObserverService().observe(directory)
            with request_container(DatabaseSettings(self.database, write=True)) as scope:
                with scope.get(Transaction):
                    actor = scope.get(RegisterSessionUseCase).run(
                        RegisterSessionCommand(observation, self.provider, native_session)
                    )
                    command = replace(
                        command, project_id=actor.project.uid, session_id=actor.session.uid
                    )
                    result = scope.get(HandleHookUseCase).run(command)
            if result.action is HookAction.PAUSE:
                return {"continue": False, "stopReason": result.message or "Execution is paused"}
            if result.action is HookAction.CONTINUE:
                return {
                    "decision": "block",
                    "reason": "Continue unfinished work:\n" + result.message,
                }
            return {}
        except Exception as error:
            return {
                "continue": False,
                "stopReason": f"Neurath hook failure: {error}. Use the management recovery/bypass path; unfinished work is preserved.",
            }

    def decode(self, payload: dict[str, object]) -> tuple[HandleHookCommand, str, str]:
        """공급자별 턴·도구 종료 계약을 정규화하고 누락된 신원을 꾸며 만들지 않는다.

        Args:
            payload: 실제 호스트의 사건 JSON 객체.

        Returns:
            tuple[HandleHookCommand, str, str]: 코어 사건, 작업 폴더, 실제 호스트 세션 ID.

        Raises:
            ValueError: 필수 식별자나 부울 필드의 형식이 잘못된 경우.
        """
        event = self._text(payload, "hook_event_name", required=True)
        session = self._text(payload, "session_id", required=True)
        directory = self._text(payload, "cwd", required=True)
        turn = self._text(payload, "turn_id" if self.provider == "codex" else "prompt_id")
        tool = self._text(payload, "tool_name")
        agent = self._text(payload, "agent_id")
        call = self._text(payload, "tool_use_id")
        repeated = payload.get("stop_hook_active", False)
        interrupted = payload.get("is_interrupt", False)
        response = payload.get("tool_response")
        if self.provider == "claude" and tool == "Bash" and isinstance(response, dict):
            interrupted = response.get("interrupted", interrupted)
        if not isinstance(repeated, bool) or not isinstance(interrupted, bool):
            raise ValueError("Hook flags must be booleans")
        resource = ""
        if event in ("PreToolUse", "PostToolUse", "PostToolUseFailure"):
            if not tool or not call:
                raise ValueError("Tool event requires a tool name and call ID")
            if tool in self.write_tools:
                resource = self._workspace(directory)
        command = HandleHookCommand(
            project_id="",
            session_id="",
            event=event,
            start_source=self._text(payload, "source"),
            turn_id=turn,
            agent_id=agent,
            tool_use_id=call,
            resource=resource,
            repeated=repeated,
            interrupted=interrupted,
            reason=self._text(payload, "error") or self._text(payload, "reason"),
            finished=self._finished(payload, event, tool),
        )
        return command, directory, session

    @staticmethod
    def _workspace(directory: str) -> str:
        """같은 Git 작업 트리의 하위 경로들을 하나의 작성 범위로 정규화한다.

        Args:
            directory: 네이티브 호출의 실제 작업 디렉터리.

        Returns:
            str: 해당 작업 트리의 루트이며 Git이 없으면 정규 작업 폴더.
        """
        resolved = Path(directory).resolve()
        try:
            result = subprocess.run(
                ["git", "-C", str(resolved), "rev-parse", "--show-toplevel"],
                capture_output=True,
                text=True,
                check=False,
                env={key: value for key, value in os.environ.items() if not key.startswith("GIT_")},
            )
        except FileNotFoundError:
            return str(resolved)
        if result.returncode != 0:
            return str(resolved)
        return str(Path(result.stdout.strip()).resolve())

    def _finished(self, payload: dict[str, object], event: str, tool: str) -> bool:
        """동기 도구 결과와 종료 코드가 확인된 셸 결과만 작성 종료로 판정한다.

        Args:
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
        if self.provider == "codex" and tool == "Bash" and isinstance(response, str):
            return True
        if not isinstance(response, dict):
            return False
        response = cast(dict[str, object], response)
        if response.get("session_id") is not None or response.get("backgroundTaskId") is not None:
            return False
        if self.provider == "claude" and tool == "Bash":
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

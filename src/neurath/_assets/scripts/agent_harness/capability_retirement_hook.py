"""보호된 harness capability와 connector의 shell retirement를 사전에 거부합니다."""

import json
import os
import shlex
import sys
from collections.abc import Mapping, Sequence
from enum import StrEnum
from pathlib import Path


class CapabilityRetirementPayloadError(ValueError):
    """PreToolUse payload나 closed command를 안전하게 정규화할 수 없습니다."""


class CapabilityRetirementDecisionCode(StrEnum):
    """Hook caller와 regression이 공유하는 stable decision code입니다."""

    HOST_MANAGED = "host-managed"
    """보호된 capability retirement가 아닌 host command입니다."""

    PROTECTED_CONNECTOR = "protected-connector"
    """Agent shell이 보호된 connector 등록을 직접 제거하려 했습니다."""

    PROTECTED_CAPABILITY = "protected-capability"
    """Agent shell이 보호된 repository capability를 직접 삭제하려 했습니다."""

    INVALID_INPUT = "invalid-input"
    """Hook payload가 canonical process command로 정규화되지 않았습니다."""


class CapabilityRetirementHookResult:
    """PreToolUse allow 또는 deny 결과를 immutable하게 보존합니다."""

    __slots__ = ("code", "exit_code", "stderr")

    def __init__(
        self,
        *,
        exit_code: int,
        code: CapabilityRetirementDecisionCode,
        stderr: str,
    ) -> None:
        """Process exit, stable code와 optional hook diagnostic을 고정합니다.

        Args:
            exit_code: Allow 또는 deny process exit code입니다.
            code: Stable hook decision code입니다.
            stderr: Vendor에 반환할 optional compact diagnostic입니다.
        """
        object.__setattr__(self, "exit_code", exit_code)
        object.__setattr__(self, "code", code)
        object.__setattr__(self, "stderr", stderr)

    exit_code: int
    """Allow이면 0, deny 또는 invalid input이면 2입니다."""

    code: CapabilityRetirementDecisionCode
    """Caller가 분기할 stable decision code입니다."""

    stderr: str
    """Deny일 때 vendor runtime에 전달할 compact JSON입니다."""

    def __setattr__(self, name: str, value: object) -> None:
        """생성된 hook result의 mutation을 거부합니다.

        Args:
            name: 변경하려 한 attribute 이름입니다.
            value: 적용하지 않을 새 값입니다.

        Raises:
            AttributeError: 생성 뒤에는 항상 발생합니다.
        """
        raise AttributeError(f"{type(self).__name__} is immutable")


class CapabilityRetirementHookApplication:
    """Closed destructive command만 식별하고 나머지 shell authority는 host에 남깁니다."""

    _PROCESS_TOOLS = frozenset(
        {
            "bash",
            "exec_command",
            "functions.exec_command",
            "shell",
            "unified_exec",
        }
    )
    _COMMAND_KEYS = ("command", "cmd", "input")
    _COMMAND_SEPARATORS = frozenset({"&&", "||", ";", "|"})
    _COMMAND_PREFIXES = frozenset({"command", "env", "sudo"})
    _PROTECTED_CONNECTORS = frozenset()
    _PROTECTED_PATHS = (".neurath",)

    def run(self, raw_input: str, cwd: Path) -> CapabilityRetirementHookResult:
        """한 process-tool payload에서 보호 대상 retirement만 fail-closed합니다.

        일반 shell 의미나 repository mutation target을 추론하지 않습니다. Agent가 과거
        cleanup에서 실제 사용한 closed destructive command family만 검사합니다.

        Args:
            raw_input: Vendor가 전달한 PreToolUse JSON 원문입니다.
            cwd: Relative deletion target을 해석할 repository root입니다.

        Returns:
            Host defer 또는 protected retirement deny 결과입니다.
        """
        try:
            payload = self._payload(raw_input)
            tool_name = self._tool_name(payload)
            command = self._command(payload)
            inputs = payload.get("tool_input", {})
            workdir = (
                inputs.get("workdir", payload.get("cwd", str(cwd)))
                if isinstance(inputs, Mapping)
                else payload.get("cwd", str(cwd))
            )
            if not isinstance(workdir, str) or not workdir:
                raise CapabilityRetirementPayloadError("process workdir must be a path")
            execution_root = Path(workdir)
            if not execution_root.is_absolute():
                execution_root = cwd / execution_root
        except (json.JSONDecodeError, CapabilityRetirementPayloadError) as error:
            return self._deny(CapabilityRetirementDecisionCode.INVALID_INPUT, str(error))
        if tool_name not in self._PROCESS_TOOLS or command is None:
            return self._allow()
        tool_use_id = payload.get("tool_use_id")
        missing_execution_root = (
            tool_name == "bash"
            and isinstance(tool_use_id, str)
            and tool_use_id.startswith("exec-")
            and bool(payload.get("turn_id"))
            and isinstance(inputs, Mapping)
            and "workdir" not in inputs
        )
        try:
            segments = self._execution_segments(
                command, None if missing_execution_root else execution_root
            )
        except CapabilityRetirementPayloadError:
            return self._deny(
                CapabilityRetirementDecisionCode.INVALID_INPUT,
                "process command quoting is invalid",
            )
        for segment, segment_root in segments:
            normalized = self._without_prefixes(segment)
            if self._removes_protected_connector(normalized):
                return self._deny(
                    CapabilityRetirementDecisionCode.PROTECTED_CONNECTOR,
                    "content cleanup does not authorize protected connector retirement; "
                    "the user must perform connector removal directly outside the agent shell",
                )
            if self._deletes_protected_capability(
                normalized, cwd, segment_root
            ):
                return self._deny(
                    CapabilityRetirementDecisionCode.PROTECTED_CAPABILITY,
                    "native host omitted execution workdir; deletion requires absolute targets "
                    "and must preserve protected capabilities"
                    if missing_execution_root
                    else "content cleanup does not authorize protected project capability retirement",
                )
        return self._allow()

    def _payload(self, raw_input: str) -> Mapping[str, object]:
        parsed: object = json.loads(raw_input)
        if not isinstance(parsed, dict) or any(not isinstance(key, str) for key in parsed):
            raise CapabilityRetirementPayloadError("PreToolUse payload must be a JSON object")
        return parsed

    def _tool_name(self, payload: Mapping[str, object]) -> str:
        value = payload.get("tool_name")
        if not isinstance(value, str) or not value.strip():
            raise CapabilityRetirementPayloadError("PreToolUse payload requires tool_name")
        return value.strip().casefold()

    def _command(self, payload: Mapping[str, object]) -> str | None:
        tool_input = payload.get("tool_input", {})
        if isinstance(tool_input, str):
            return tool_input if tool_input.strip() else None
        if not isinstance(tool_input, Mapping):
            raise CapabilityRetirementPayloadError("tool_input must be an object or string")
        for key in self._COMMAND_KEYS:
            value = tool_input.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return None

    def _execution_segments(
        self, command: str, execution_root: Path | None
    ) -> tuple[tuple[tuple[str, ...], Path | None], ...]:
        """Bind each inspected command to its effective execution directory."""
        return tuple((segment, execution_root) for segment in self._segments(command))

    def _segments(self, command: str) -> tuple[tuple[str, ...], ...]:
        try:
            tokens = tuple(shlex.split(command, posix=True))
        except ValueError as error:
            raise CapabilityRetirementPayloadError("process command quoting is invalid") from error
        segments: list[tuple[str, ...]] = []
        start = 0
        for index, token in enumerate(tokens):
            if token not in self._COMMAND_SEPARATORS:
                continue
            if index > start:
                segments.append(tokens[start:index])
            start = index + 1
        if start < len(tokens):
            segments.append(tokens[start:])
        return tuple(segment for segment in segments if segment)

    def _without_prefixes(self, segment: tuple[str, ...]) -> tuple[str, ...]:
        index = 0
        while index < len(segment):
            token = segment[index]
            if token in self._COMMAND_PREFIXES or (
                "=" in token and not token.startswith(("/", "./", "../"))
            ):
                index += 1
                continue
            break
        return segment[index:]

    def _removes_protected_connector(self, segment: tuple[str, ...]) -> bool:
        if len(segment) < 4 or Path(segment[0]).name.casefold() != "codex":
            return False
        if tuple(token.casefold() for token in segment[1:3]) != ("mcp", "remove"):
            return False
        targets = {token.casefold() for token in segment[3:] if not token.startswith("-")}
        return bool(targets & self._PROTECTED_CONNECTORS)

    def _deletes_protected_capability(
        self, segment: tuple[str, ...], cwd: Path, execution_root: Path | None
    ) -> bool:
        if not segment:
            return False
        executable = Path(segment[0]).name.casefold()
        arguments: tuple[str, ...]
        if executable in {"rm", "unlink"}:
            arguments = segment[1:]
        elif executable == "git" and len(segment) >= 2 and segment[1].casefold() == "rm":
            arguments = segment[2:]
        elif executable == "git" and len(segment) >= 2 and segment[1].casefold() == "clean":
            dry_run = any(token in {"-n", "--dry-run"} for token in segment[2:])
            return not dry_run
        elif executable == "find" and "-delete" in segment:
            arguments = tuple(token for token in segment[1:] if token != "-delete")
        else:
            return False
        targets = tuple(token for token in arguments if token != "--" and not token.startswith("-"))
        return any(self._target_overlaps_protected(token, cwd, execution_root) for token in targets)

    def _target_overlaps_protected(
        self, raw_target: str, cwd: Path, execution_root: Path | None
    ) -> bool:
        if execution_root is None and not Path(raw_target).is_absolute():
            return True
        positions = [raw_target.index(marker) for marker in ("*", "?", "[") if marker in raw_target]
        if positions:
            raw_target = raw_target[: min(positions)]
        target = Path(raw_target)
        target = target if target.is_absolute() else (execution_root or cwd) / target
        target = Path(os.path.abspath(target))
        for relative_path in self._PROTECTED_PATHS:
            protected = Path(os.path.abspath(cwd / relative_path))
            if positions and str(protected).startswith(str(target)):
                return True
            if target == protected or target in protected.parents or protected in target.parents:
                return True
        return False

    def _allow(self) -> CapabilityRetirementHookResult:
        return CapabilityRetirementHookResult(
            exit_code=0,
            code=CapabilityRetirementDecisionCode.HOST_MANAGED,
            stderr="",
        )

    def _deny(
        self,
        code: CapabilityRetirementDecisionCode,
        reason: str,
    ) -> CapabilityRetirementHookResult:
        payload = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": (
                    f"Neurath capability retirement guard [{code.value}]: {reason}"
                ),
            }
        }
        return CapabilityRetirementHookResult(
            exit_code=2,
            code=code,
            stderr=json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
        )


class CapabilityRetirementHookCommand:
    """Process stdin과 cwd를 stateless hook application에 전달합니다."""

    def run(self, arguments: Sequence[str]) -> int:
        """인자 없는 canonical PreToolUse entrypoint만 실행합니다.

        Args:
            arguments: Process entrypoint positional arguments입니다.

        Returns:
            Hook allow 또는 deny exit code입니다.
        """
        if tuple(arguments):
            return 2
        from neurath.hosts.capabilities import capability_policy

        result = capability_policy(Path.cwd()).run(sys.stdin.read(), Path.cwd())
        if result.stderr:
            sys.stderr.write(result.stderr)
        return result.exit_code


if __name__ == "__main__":
    raise SystemExit(CapabilityRetirementHookCommand().run(sys.argv[1:]))

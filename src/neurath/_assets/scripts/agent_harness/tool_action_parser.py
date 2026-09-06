"""구조화된 repository edit의 target만 정규화하고 host tool 의미는 해석하지 않습니다."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from enum import StrEnum
from pathlib import Path
from typing import ClassVar

from scripts.agent_harness.material_action import canonical_material_target


class ToolActionPayloadError(ValueError):
    """Raw hook payload를 bounded tool action으로 정규화할 수 없습니다."""


class ToolActionEffect(StrEnum):
    """한 tool invocation에서 repository harness가 맡는 책임을 구분합니다."""

    HOST_MANAGED = "host-managed"
    """Host, provider, sandbox와 사용자 승인이 tool authority를 소유합니다."""

    MATERIAL_MUTATION = "material-mutation"
    """Structured file edit가 exact repository target과 readback을 요구합니다."""


class ToolActionRequest:
    """Structured PreTool과 PostTool hook이 공유하는 canonical request입니다."""

    __slots__ = (
        "command",
        "effect",
        "input",
        "invocation_id",
        "name",
        "request_digest",
        "runtime_agent_id",
        "runtime_session_id",
        "targets",
        "workdir",
    )

    def __init__(
        self,
        *,
        name: str,
        input_payload: Mapping[str, object],
        workdir: Path,
        command: str | None,
        targets: Sequence[str],
        invocation_id: str | None,
        request_digest: str,
        effect: ToolActionEffect,
        runtime_agent_id: str | None = None,
        runtime_session_id: str | None = None,
    ) -> None:
        """정규화된 tool request를 immutable value로 만듭니다.

        Args:
            name: Runtime namespace 차이를 제거한 tool 이름입니다.
            input_payload: Digest와 structured target 추출에 쓰는 detached 입력입니다.
            workdir: Relative target을 해석할 canonical 작업 경로입니다.
            command: Structured patch 또는 host process가 제공한 optional 원문입니다.
            targets: Payload에서 증명한 exact file target 목록입니다.
            invocation_id: PreTool과 PostTool receipt를 연결하는 optional identity입니다.
            request_digest: Tool 이름, 입력과 workdir을 결속한 digest입니다.
            effect: Repository harness가 맡을 bounded effect입니다.
            runtime_agent_id: Vendor payload가 제공한 optional actor identity입니다.
            runtime_session_id: Vendor payload가 제공한 optional session identity입니다.
        """
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "input", dict(input_payload))
        object.__setattr__(self, "workdir", workdir)
        object.__setattr__(self, "command", command)
        object.__setattr__(self, "targets", tuple(targets))
        object.__setattr__(self, "invocation_id", invocation_id)
        object.__setattr__(self, "request_digest", request_digest)
        object.__setattr__(self, "effect", effect)
        object.__setattr__(self, "runtime_agent_id", runtime_agent_id)
        object.__setattr__(self, "runtime_session_id", runtime_session_id)

    name: str
    """Runtime namespace 차이를 제거한 tool 이름입니다."""
    input: Mapping[str, object]
    """Request digest와 target 추출에 사용한 detached 입력입니다."""
    workdir: Path
    """Relative target 해석 기준이 되는 canonical 작업 경로입니다."""
    command: str | None
    """Structured patch 또는 host process가 제공한 optional 원문입니다."""
    targets: tuple[str, ...]
    """Structured edit payload에서 증명한 exact file target입니다."""
    invocation_id: str | None
    """PreTool과 PostTool delivery를 연결하는 optional invocation identity입니다."""
    request_digest: str
    """Tool identity, 입력과 workdir을 결속한 canonical digest입니다."""
    effect: ToolActionEffect
    """Repository harness가 이 invocation에서 맡을 bounded effect입니다."""
    runtime_agent_id: str | None
    """Vendor payload가 증명한 optional runtime actor identity입니다."""
    runtime_session_id: str | None
    """Vendor payload가 증명한 optional runtime session identity입니다."""

    def __setattr__(self, name: str, value: object) -> None:
        """생성된 request의 mutation을 거부합니다.

        Args:
            name: 변경을 시도한 attribute 이름입니다.
            value: 적용되지 않는 새 값입니다.

        Raises:
            AttributeError: Request는 생성 뒤 항상 immutable이므로 발생합니다.
        """
        raise AttributeError(f"{type(self).__name__} is immutable")


class ToolActionResult:
    """PostTool payload를 request-bound fixed-size receipt로 축소합니다."""

    __slots__ = ("duration_milliseconds", "output_digest", "request", "succeeded")

    def __init__(
        self,
        *,
        request: ToolActionRequest,
        succeeded: bool,
        output_digest: str,
        duration_milliseconds: int | None,
    ) -> None:
        """실행 결과를 raw output 없는 immutable receipt로 만듭니다.

        Args:
            request: 결과가 결속된 canonical request입니다.
            succeeded: Vendor event와 bounded result가 나타낸 성공 여부입니다.
            output_digest: Raw output 대신 보존하는 canonical result digest입니다.
            duration_milliseconds: Runtime이 제공한 optional bounded duration입니다.
        """
        object.__setattr__(self, "request", request)
        object.__setattr__(self, "succeeded", succeeded)
        object.__setattr__(self, "output_digest", output_digest)
        object.__setattr__(self, "duration_milliseconds", duration_milliseconds)

    request: ToolActionRequest
    """이 result가 결속된 canonical request입니다."""
    succeeded: bool
    """Vendor event와 bounded result가 나타낸 성공 여부입니다."""
    output_digest: str
    """Raw output을 보존하지 않는 canonical result digest입니다."""
    duration_milliseconds: int | None
    """Runtime이 제공한 optional non-negative duration입니다."""

    def __setattr__(self, name: str, value: object) -> None:
        """생성된 result의 mutation을 거부합니다.

        Args:
            name: 변경을 시도한 attribute 이름입니다.
            value: 적용되지 않는 새 값입니다.

        Raises:
            AttributeError: Result는 생성 뒤 항상 immutable이므로 발생합니다.
        """
        raise AttributeError(f"{type(self).__name__} is immutable")


class ToolActionParser:
    """Structured edit path만 읽고 나머지 tool semantics는 host에 남깁니다."""

    _STRUCTURED_MUTATION_TOOLS = frozenset({
        "apply_patch",
        "edit",
        "multiedit",
        "notebookedit",
        "write",
    })
    _ALIASES: ClassVar[dict[str, str]] = {
        "functions.apply_patch": "apply_patch",
        "functions.edit": "edit",
        "functions.multiedit": "multiedit",
        "functions.notebookedit": "notebookedit",
        "functions.write": "write",
        "tools.apply_patch": "apply_patch",
    }
    _PROCESS_TOOLS = frozenset({
        "bash",
        "exec_command",
        "functions.exec_command",
        "shell",
        "unified_exec",
    })
    _IDENTITY_PATTERN = re.compile(r"[A-Za-z0-9._:-]+")

    def parse_request(self, raw_input: str, cwd: Path) -> ToolActionRequest:
        """Hook request를 structured target 또는 host-managed request로 정규화합니다.

        Args:
            raw_input: Vendor hook이 전달한 JSON object 문자열입니다.
            cwd: Payload에 workdir이 없을 때 사용할 canonical 기준 경로입니다.

        Returns:
            Tool 의미를 추론하지 않은 bounded canonical request입니다.
        """
        payload = self._payload(raw_input)
        name = self._tool_name(payload)
        input_payload = dict(self._input_payload(payload))
        workdir = self._workdir(payload, input_payload, cwd)
        command = self._optional_text(input_payload, ("command", "cmd", "input"))
        effect = (
            ToolActionEffect.MATERIAL_MUTATION
            if name in self._STRUCTURED_MUTATION_TOOLS
            else ToolActionEffect.HOST_MANAGED
        )
        targets = (
            self._structured_targets(name, input_payload, workdir, command)
            if effect is ToolActionEffect.MATERIAL_MUTATION
            else ()
        )
        return ToolActionRequest(
            name=name,
            input_payload=input_payload,
            workdir=workdir,
            command=command,
            targets=targets,
            invocation_id=self._invocation_id(payload),
            request_digest=self._request_digest(name, input_payload, workdir),
            effect=effect,
            runtime_agent_id=self._optional_identity(payload, "agent_id"),
            runtime_session_id=self._optional_identity(payload, "session_id"),
        )

    def parse_result(self, raw_input: str, cwd: Path) -> ToolActionResult:
        """PostTool payload를 request-bound bounded result로 정규화합니다.

        Args:
            raw_input: Vendor result와 original request가 들어 있는 JSON 문자열입니다.
            cwd: Relative workdir과 target을 해석할 canonical 기준 경로입니다.

        Returns:
            Raw output 대신 digest와 bounded telemetry만 가진 result입니다.
        """
        payload = self._payload(raw_input)
        request = self.parse_request(raw_input, cwd)
        output = self._result_payload(payload)
        return ToolActionResult(
            request=request,
            succeeded=not self._is_failure(
                payload,
                output,
                process_status=request.name in self._PROCESS_TOOLS,
            ),
            output_digest=hashlib.sha256(self._canonical_json(output)).hexdigest(),
            duration_milliseconds=self._duration_milliseconds(payload),
        )

    def _payload(self, raw_input: str) -> Mapping[str, object]:
        try:
            payload: object = json.loads(raw_input)
        except json.JSONDecodeError as error:
            raise ToolActionPayloadError("tool hook stdin must be valid JSON") from error
        if not isinstance(payload, dict) or any(not isinstance(key, str) for key in payload):
            raise ToolActionPayloadError("tool hook stdin must be a JSON object")
        return payload

    def _tool_name(self, payload: Mapping[str, object]) -> str:
        value = payload.get("tool_name")
        if not isinstance(value, str) or not value.strip():
            raise ToolActionPayloadError("tool hook payload requires tool_name")
        normalized = value.strip().casefold()
        return self._ALIASES.get(normalized, normalized)

    def _input_payload(self, payload: Mapping[str, object]) -> Mapping[str, object]:
        value = payload.get("tool_input", {})
        if isinstance(value, str):
            return {"input": value}
        if isinstance(value, dict) and all(isinstance(key, str) for key in value):
            return {str(key): item for key, item in value.items()}
        raise ToolActionPayloadError("tool_input must be an object or string")

    def _workdir(
        self,
        payload: Mapping[str, object],
        input_payload: Mapping[str, object],
        cwd: Path,
    ) -> Path:
        value = self._optional_text(input_payload, ("workdir", "cwd", "working_dir"))
        if value is None:
            top_level = payload.get("cwd")
            value = top_level if isinstance(top_level, str) and top_level.strip() else None
        candidate = cwd if value is None else Path(value)
        if not candidate.is_absolute():
            candidate = cwd / candidate
        return canonical_material_target(candidate)

    def _structured_targets(
        self,
        name: str,
        input_payload: Mapping[str, object],
        workdir: Path,
        command: str | None,
    ) -> tuple[str, ...]:
        candidates = list(self._mapping_target_paths(input_payload))
        if name == "multiedit":
            edits = input_payload.get("edits")
            if not isinstance(edits, list) or not edits:
                raise ToolActionPayloadError("MultiEdit requires a non-empty edits list")
            for edit in edits:
                if not isinstance(edit, Mapping):
                    raise ToolActionPayloadError("MultiEdit edits must be objects")
                candidates.extend(self._mapping_target_paths(edit))
        if name == "apply_patch":
            if command is None:
                raise ToolActionPayloadError("apply_patch requires literal patch input")
            candidates.extend(self._patch_paths(command))
        resolved = (
            str(self._resolve_path(candidate, workdir)) for candidate in dict.fromkeys(candidates)
        )
        return tuple(sorted(set(resolved)))

    def _mapping_target_paths(self, payload: Mapping[str, object]) -> tuple[str, ...]:
        candidates: list[str] = []
        for key in ("file_path", "notebook_path", "path", "target_path"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                candidates.append(value.strip())
        values = payload.get("paths")
        if isinstance(values, list):
            candidates.extend(
                value.strip() for value in values if isinstance(value, str) and value.strip()
            )
        return tuple(candidates)

    def _patch_paths(self, patch: str) -> tuple[str, ...]:
        paths: list[str] = []
        prefixes = (
            "*** Add File: ",
            "*** Delete File: ",
            "*** Update File: ",
            "*** Move to: ",
        )
        for line in patch.splitlines():
            for prefix in prefixes:
                if not line.startswith(prefix):
                    continue
                target = line.removeprefix(prefix).strip()
                if not target:
                    raise ToolActionPayloadError("patch target path must be non-empty")
                paths.append(target)
                break
        return tuple(paths)

    def _resolve_path(self, value: str, workdir: Path) -> Path:
        candidate = Path(value)
        if not candidate.is_absolute():
            candidate = workdir / candidate
        return canonical_material_target(candidate)

    def _optional_identity(self, payload: Mapping[str, object], key: str) -> str | None:
        value = payload.get(key)
        if value is None:
            return None
        if (
            not isinstance(value, str)
            or not value
            or value != value.strip()
            or self._IDENTITY_PATTERN.fullmatch(value) is None
        ):
            raise ToolActionPayloadError(f"{key} must be a canonical identity token")
        return value

    def _invocation_id(self, payload: Mapping[str, object]) -> str | None:
        for key in ("tool_use_id", "toolUseId"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    def _request_digest(
        self,
        name: str,
        input_payload: Mapping[str, object],
        workdir: Path,
    ) -> str:
        payload = {
            "tool_name": name,
            "tool_input": dict(input_payload),
            "workdir": str(workdir),
        }
        return hashlib.sha256(self._canonical_json(payload)).hexdigest()

    def _result_payload(self, payload: Mapping[str, object]) -> object:
        for key in (
            "tool_response",
            "tool_result",
            "tool_output",
            "result",
            "error",
            "reason",
        ):
            if key in payload:
                return payload[key]
        return None

    def _duration_milliseconds(self, payload: Mapping[str, object]) -> int | None:
        value = payload.get("duration_ms")
        if value is None:
            return None
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ToolActionPayloadError("duration_ms must be a non-negative integer")
        return value

    def _is_failure(
        self,
        payload: Mapping[str, object],
        result: object,
        *,
        process_status: bool,
    ) -> bool:
        if payload.get("hook_event_name") == "PermissionDenied":
            return True
        if self._mapping_reports_failure(payload, process_status=process_status):
            return True
        if isinstance(result, Mapping) and self._mapping_reports_failure(
            result,
            process_status=process_status,
        ):
            return True
        return any(
            isinstance(nested, Mapping)
            and self._mapping_reports_failure(nested, process_status=process_status)
            for key in ("tool_response", "tool_result", "tool_output", "result")
            if (nested := payload.get(key)) is not None
        )

    def _mapping_reports_failure(
        self,
        payload: Mapping[str, object],
        *,
        process_status: bool,
    ) -> bool:
        if (
            payload.get("is_error") is True
            or payload.get("tool_error") is not None
            or payload.get("error") is not None
        ):
            return True
        for key in ("exit_code", "returncode", "status"):
            value = payload.get(key)
            if (
                isinstance(value, int)
                and not isinstance(value, bool)
                and value != 0
                and (key != "status" or process_status)
            ):
                return True
            if isinstance(value, str) and value.strip().casefold() in {
                "error",
                "failed",
                "failure",
            }:
                return True
        return False

    def _canonical_json(self, value: object) -> bytes:
        try:
            return json.dumps(
                value,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        except (TypeError, ValueError) as error:
            raise ToolActionPayloadError("tool payload must be canonical JSON") from error

    def _optional_text(
        self,
        payload: Mapping[str, object],
        keys: Sequence[str],
    ) -> str | None:
        for key in keys:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

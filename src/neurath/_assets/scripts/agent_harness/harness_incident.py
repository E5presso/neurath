"""Runtime-bound session incident lifecycle과 resolution evidence를 관리합니다."""

import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from scripts.agent_harness.bounded_process import run_bounded_process
from scripts.agent_harness.repository_readback import (
    RepositoryReadbackError,
    RepositoryWorktreeReadback,
)
from scripts.agent_harness.session_kernel import (
    HarnessIncidentEscalated,
    HarnessIncidentEvidenceSuperseded,
    HarnessIncidentRecord,
    HarnessIncidentRecorded,
    HarnessIncidentResolved,
    HarnessIncidentsRefreshed,
    HarnessIncidentStatus,
    HarnessRegressionReceipt,
    IncidentId,
    ProcessState,
    SessionKernelError,
    SessionLocator,
    TransitionRejected,
)
from scripts.agent_harness.state_handle import (
    RuntimeEnvironmentResolver,
    RuntimeIdentityError,
    StateHandle,
)

ALLOWED_REGRESSION_MODULES = frozenset({
    "scripts.agent_harness",
    "scripts.deployment_harness",
    "scripts.e2e_harness",
    "scripts.frontend_harness",
    "scripts.harness_lint",
    "scripts.local_surface_harness",
    "scripts.skill_harness",
    "scripts.static_harness",
    "scripts.workspace_harness",
    "scripts.workspace_hooks.root_static_harness",
    "scripts.workspace_hooks.subproject_precommit",
})
NONEXECUTING_REGRESSION_ARGUMENTS = frozenset({
    "-h",
    "--help",
    "-V",
    "--version",
    "--collect-only",
    "--co",
    "--fixtures",
    "--fixtures-per-test",
    "--markers",
    "--setup-only",
    "--setup-plan",
    "--trace-config",
    "--debug",
})


class HarnessIncidentValidationError(ValueError):
    """Incident ledger 또는 resolution evidence가 contract를 위반했음을 나타냅니다."""


class HarnessRegressionExecutionError(HarnessIncidentValidationError):
    """Allowlisted regression process의 bounded transient failure diagnostic입니다."""

    def __init__(
        self,
        command: str,
        exit_code: int,
        diagnostic_tail: str,
        output_sha256: str,
    ) -> None:
        """Command identity, exit, capped tail과 full output digest를 보존합니다.

        Args:
            command: 실패한 exact allowlisted command입니다.
            exit_code: Verifier process의 nonzero exit code입니다.
            diagnostic_tail: 현재 응답에만 노출할 bounded sanitized output tail입니다.
            output_sha256: 전체 stdout/stderr bytes의 SHA-256 identity입니다.
        """
        super().__init__(f"regression command failed with exit {exit_code}: {command}")
        self.command = command
        """실패한 exact allowlisted command입니다."""
        self.exit_code = exit_code
        """Verifier process의 nonzero exit code입니다."""
        self.diagnostic_tail = diagnostic_tail
        """현재 CLI 응답에만 쓰는 최대 8192자의 sanitized output tail입니다."""
        self.output_sha256 = output_sha256
        """전체 stdout/stderr bytes를 raw 저장 없이 식별하는 SHA-256입니다."""


class HarnessIncidentApplication:
    """Runtime-bound StateHandle을 통해서만 session incident projection을 갱신합니다."""

    def __init__(self, handle: StateHandle, worktree: Path) -> None:
        """Exact session authority와 repository evidence 경계를 결속합니다.

        Args:
            handle: Runtime identity와 current actor를 검증한 path-free state facade입니다.
            worktree: Fix path와 regression command를 검증할 current repository입니다.
        """
        self._handle = handle
        self._worktree = worktree.resolve()
        self._warnings: tuple[str, ...] = ()

    @property
    def warnings(self) -> tuple[str, ...]:
        """마지막 mutation에서 발견한 non-blocking harness design 경고를 반환합니다.

        Returns:
            Deterministic gate가 없는 resolution 등에 대한 bounded warning입니다.
        """
        return self._warnings

    def record(self, rule_id: str, symptom: str) -> HarnessIncidentRecord:
        """현재 actor가 관찰한 harness failure를 새 open occurrence로 기록합니다.

        Args:
            rule_id: 반복 occurrence를 같은 근본 invariant로 묶는 stable identity입니다.
            symptom: 실행 중 직접 관찰한 재현 가능한 workflow failure입니다.

        Returns:
            Optimistic transaction으로 commit된 typed open incident입니다.

        Raises:
            TransitionRejected: 같은 rule의 open occurrence가 이미 있으면 발생합니다.
        """
        self._warnings = ()
        occurrence_id = IncidentId(uuid4().hex)
        recorded_at = datetime.now(UTC).isoformat()
        state = self._handle.apply(
            HarnessIncidentRecorded(
                session_id=self._handle.session_id,
                occurrence_id=occurrence_id,
                rule_id=rule_id,
                actor_id=self._handle.actor_id,
                symptom=symptom,
                recorded_at=recorded_at,
                idempotency_key=f"harness-incident:record:{occurrence_id}",
            )
        )
        return state.incidents[occurrence_id]

    def resolve(
        self,
        incident_id: str,
        root_cause: str,
        harness_fix: list[str],
        regression_commands: list[str],
    ) -> HarnessIncidentRecord:
        """Open occurrence를 실행 검증된 root-cause fix와 함께 resolved로 닫습니다.

        Args:
            incident_id: Stable rule 또는 exact occurrence identity입니다.
            root_cause: 재발을 설명하는 비어 있지 않은 근본 원인입니다.
            harness_fix: 원인을 제거한 durable repository-relative path입니다.
            regression_commands: Application이 직접 실행할 deterministic checks입니다.

        Returns:
            Complete resolution evidence가 commit된 typed incident입니다.

        Raises:
            HarnessIncidentValidationError: Fix 또는 regression evidence가 contract를
                위반하면 발생합니다.
            TransitionRejected: Matching open occurrence가 없거나 concurrent transition이
                먼저 완료되면 발생합니다.
        """
        snapshot = self._handle.inspect()
        incident = self._find_incident(snapshot, incident_id, HarnessIncidentStatus.OPEN)
        self._warnings = validate_harness_fix_paths(self._worktree, list(harness_fix))
        raw_receipts = run_regression_commands(self._worktree, regression_commands)
        validate_resolution_evidence(
            self._worktree,
            list(harness_fix),
            list(raw_receipts),
            replay_commands=False,
        )
        receipts = self._typed_receipts(raw_receipts)
        resolved_at = datetime.now(UTC).isoformat()
        state = self._handle.apply(
            HarnessIncidentResolved(
                session_id=self._handle.session_id,
                occurrence_id=incident.id,
                actor_id=self._handle.actor_id,
                root_cause=root_cause,
                harness_fix=tuple(harness_fix),
                regression_evidence=receipts,
                resolved_at=resolved_at,
                idempotency_key=f"harness-incident:resolve:{incident.id}:{resolved_at}",
            )
        )
        return state.incidents[incident.id]

    def escalate(
        self,
        incident_id: str,
        summary: str,
        reproduction_commands: list[str],
    ) -> HarnessIncidentRecord:
        """Open occurrence와 재현 정보를 durable fix의 loop owner에게 이관합니다.

        Args:
            incident_id: Stable rule 또는 exact occurrence identity입니다.
            summary: Loop owner가 수정을 이어받는 데 필요한 handoff 설명입니다.
            reproduction_commands: 결함을 다시 관찰할 command입니다.

        Returns:
            Complete handoff evidence가 commit된 escalated incident입니다.

        Raises:
            HarnessIncidentValidationError: Summary 또는 재현 command가 비었으면
                발생합니다.
            TransitionRejected: Matching open occurrence가 없으면 발생합니다.
        """
        if not summary.strip():
            raise HarnessIncidentValidationError("escalation summary must be non-empty")
        commands = tuple(command.strip() for command in reproduction_commands)
        if not commands or any(not command for command in commands):
            raise HarnessIncidentValidationError(
                "escalation requires at least one reproduction command"
            )
        self._warnings = ()
        incident = self._find_incident(
            self._handle.inspect(),
            incident_id,
            HarnessIncidentStatus.OPEN,
        )
        escalated_at = datetime.now(UTC).isoformat()
        state = self._handle.apply(
            HarnessIncidentEscalated(
                session_id=self._handle.session_id,
                occurrence_id=incident.id,
                actor_id=self._handle.actor_id,
                summary=summary,
                reproduction_commands=commands,
                escalated_at=escalated_at,
                idempotency_key=f"harness-incident:escalate:{incident.id}:{escalated_at}",
            )
        )
        return state.incidents[incident.id]

    def refresh(
        self,
        incident_ids: list[str],
        regression_commands: list[str] | None = None,
    ) -> tuple[HarnessIncidentRecord, ...]:
        """Resolved occurrences의 current fix receipt를 한 command batch로 원자 갱신합니다.

        Args:
            incident_ids: Stable rule 또는 occurrence selector의 non-empty unique 목록입니다.
            regression_commands: Batch 전체에 한 번 실행할 command입니다. 단일 target에서
                생략하면 stored receipt command를 다시 사용합니다.

        Returns:
            입력 selector 순서에 맞춘 refreshed typed incident tuple입니다.

        Raises:
            HarnessIncidentValidationError: Selector, stored evidence, batch command가
                refresh contract를 위반하면 발생합니다.
            TransitionRejected: External command 실행 중 target evidence가 바뀌면
                발생합니다.
        """
        if not incident_ids or any(not incident_id.strip() for incident_id in incident_ids):
            raise HarnessIncidentValidationError("incident_ids must be a non-empty array")
        if len(set(incident_ids)) != len(incident_ids):
            raise HarnessIncidentValidationError("incident_ids must be unique")
        if len(incident_ids) > 1 and regression_commands is None:
            raise HarnessIncidentValidationError(
                "batch refresh requires explicit regression_commands"
            )
        snapshot = self._handle.inspect()
        incidents = tuple(
            self._find_incident(snapshot, incident_id, HarnessIncidentStatus.RESOLVED)
            for incident_id in incident_ids
        )
        if len({incident.id for incident in incidents}) != len(incidents):
            raise HarnessIncidentValidationError("incident_ids must resolve to unique occurrences")
        for incident in incidents:
            validate_harness_fix_paths(
                self._worktree,
                list(incident.harness_fix),
                require_current_branch_change=False,
            )
        commands = regression_commands
        if commands is None:
            commands = [receipt.command for receipt in incidents[0].regression_evidence]
        raw_receipts = run_regression_commands(self._worktree, list(commands))
        for incident in incidents:
            validate_resolution_evidence(
                self._worktree,
                list(incident.harness_fix),
                list(raw_receipts),
                replay_commands=False,
                require_current_branch_change=False,
            )
        self._warnings = ()
        receipts = self._typed_receipts(raw_receipts)
        refreshed_at = datetime.now(UTC).isoformat()
        state = self._handle.apply(
            HarnessIncidentsRefreshed(
                session_id=self._handle.session_id,
                actor_id=self._handle.actor_id,
                expected_incidents=incidents,
                regression_evidence=receipts,
                refreshed_at=refreshed_at,
                idempotency_key=(
                    "harness-incident:refresh:"
                    f"{','.join(str(incident.id) for incident in incidents)}:{refreshed_at}"
                ),
            )
        )
        return tuple(state.incidents[incident.id] for incident in incidents)

    def supersede(
        self,
        incident_id: str,
        harness_fix: list[str],
        regression_commands: list[str],
    ) -> HarnessIncidentRecord:
        """Obsolete resolution evidence를 current replacement evidence로 교체합니다.

        Args:
            incident_id: Stable rule 또는 exact resolved occurrence identity입니다.
            harness_fix: Current가 될 replacement durable harness path입니다.
            regression_commands: Replacement를 검증할 deterministic checks입니다.

        Returns:
            Previous evidence archive와 current replacement가 commit된 incident입니다.

        Raises:
            HarnessIncidentValidationError: Replacement path 또는 receipt가 invalid하면
                발생합니다.
            TransitionRejected: External verification 중 current evidence가 바뀌면
                발생합니다.
        """
        incident = self._find_incident(
            self._handle.inspect(),
            incident_id,
            HarnessIncidentStatus.RESOLVED,
        )
        self._warnings = validate_harness_fix_paths(self._worktree, list(harness_fix))
        raw_receipts = run_regression_commands(self._worktree, regression_commands)
        validate_resolution_evidence(
            self._worktree,
            list(harness_fix),
            list(raw_receipts),
            replay_commands=False,
        )
        receipts = self._typed_receipts(raw_receipts)
        superseded_at = datetime.now(UTC).isoformat()
        state = self._handle.apply(
            HarnessIncidentEvidenceSuperseded(
                session_id=self._handle.session_id,
                actor_id=self._handle.actor_id,
                expected_incident=incident,
                harness_fix=tuple(harness_fix),
                regression_evidence=receipts,
                superseded_at=superseded_at,
                idempotency_key=f"harness-incident:supersede:{incident.id}:{superseded_at}",
            )
        )
        return state.incidents[incident.id]

    def _find_incident(
        self,
        state: ProcessState,
        selector: str,
        status: HarnessIncidentStatus,
    ) -> HarnessIncidentRecord:
        normalized_selector = selector.strip()
        if not normalized_selector:
            raise HarnessIncidentValidationError("incident_id must be non-empty")
        exact = state.incidents.get(IncidentId(normalized_selector))
        if exact is not None and exact.status is status:
            return exact
        candidates = tuple(
            incident
            for incident in state.incidents.values()
            if incident.rule_id == normalized_selector and incident.status is status
        )
        if not candidates:
            raise TransitionRejected(f"{status.value} incident not found: {normalized_selector}")
        return max(candidates, key=lambda incident: (incident.recorded_at, str(incident.id)))

    def _typed_receipts(
        self,
        receipts: list[dict[str, object]],
    ) -> tuple[HarnessRegressionReceipt, ...]:
        typed: list[HarnessRegressionReceipt] = []
        for receipt in receipts:
            command = receipt.get("command")
            exit_code = receipt.get("exit_code")
            head_sha = receipt.get("head_sha")
            verified_at = receipt.get("verified_at")
            output_sha256 = receipt.get("output_sha256")
            if (
                not isinstance(command, str)
                or not isinstance(exit_code, int)
                or isinstance(exit_code, bool)
                or not isinstance(head_sha, str)
                or not isinstance(verified_at, str)
                or not isinstance(output_sha256, str)
            ):
                raise HarnessIncidentValidationError("invalid regression receipt shape")
            typed.append(
                HarnessRegressionReceipt(
                    command,
                    exit_code,
                    head_sha,
                    verified_at,
                    output_sha256,
                )
            )
        return tuple(typed)


def validate_resolution_evidence(
    worktree: Path,
    harness_fix: list[object],
    regression_evidence: list[object],
    *,
    replay_commands: bool = True,
    require_current_branch_change: bool = True,
) -> tuple[str, ...]:
    """Resolution이 committed fix와 실행된 command receipt를 포함하는지 검증합니다.

    Args:
        worktree: Harness fix 경로를 해석할 repository worktree입니다.
        harness_fix: Incident를 교정한 repository-relative 파일 경로 목록입니다.
        regression_evidence: CLI가 실행해 만든 structured command receipt 목록입니다.
        replay_commands: Stored output hash와 현재 실행 결과를 대조할지 여부입니다.
        require_current_branch_change: 새 resolution처럼 fix가 현재 branch delta여야 하는지 여부입니다.

    Returns:
        코드 게이트가 없을 때의 경고 목록이며 있으면 비어 있습니다.

    Raises:
        HarnessIncidentValidationError: Fix 또는 evidence가 resolution contract를 어길 때 발생합니다.
    """
    fix_paths = _require_nonempty_strings(harness_fix, "harness_fix")
    warnings = validate_harness_fix_paths(
        worktree,
        list(fix_paths),
        require_current_branch_change=require_current_branch_change,
    )
    _validate_regression_receipts(
        worktree.resolve(),
        fix_paths,
        regression_evidence,
        replay_commands=replay_commands,
    )
    return warnings


def validate_harness_fix_paths(
    worktree: Path,
    harness_fix: list[object],
    *,
    require_current_branch_change: bool = True,
) -> tuple[str, ...]:
    """Incident fix 경로가 실재하고 현재 branch에 반영된 committed 파일인지 검증합니다.

    Args:
        worktree: Harness fix 경로를 해석할 repository worktree입니다.
        harness_fix: Incident를 교정한 repository-relative 파일 경로 목록입니다.
        require_current_branch_change: 새 fix가 현재 branch에서 실제 변경됐어야 하는지 여부입니다.

    Returns:
        코드 게이트가 없을 때의 경고 목록이며 있으면 비어 있습니다.

    Raises:
        HarnessIncidentValidationError: Fix가 미변경, dirty, 또는 실재하지 않을 때 발생합니다.
    """
    fixes = _require_nonempty_strings(harness_fix, "harness_fix")
    deterministic_gate_found = False
    worktree_root = worktree.resolve()
    relative_paths: list[Path] = []
    for value in fixes:
        relative_path = Path(value)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise HarnessIncidentValidationError(
                f"harness_fix must be repository-relative: {value}"
            )
        fix_path = (worktree_root / relative_path).resolve()
        if worktree_root not in fix_path.parents or not fix_path.is_file():
            raise HarnessIncidentValidationError(f"harness_fix path does not exist: {value}")
        relative_paths.append(relative_path)
    changed_paths = _changed_paths(worktree_root) if require_current_branch_change else set()
    for relative_path in relative_paths:
        value = relative_path.as_posix()
        if not _is_tracked_clean_path(worktree_root, relative_path):
            raise HarnessIncidentValidationError(
                f"harness_fix path must be committed and clean: {value}"
            )
        if require_current_branch_change and relative_path.as_posix() not in changed_paths:
            raise HarnessIncidentValidationError(
                f"harness_fix path is not changed on the current branch: {value}"
            )
        deterministic_gate_found = deterministic_gate_found or _is_deterministic_gate_path(
            relative_path
        )
    if deterministic_gate_found:
        return ()
    # 산문만으로 원인을 없애는 해결도 정상 경로입니다(ADR-0023). 코드 게이트가 필요한지는
    # 해석이므로 강제하지 않고 경고만 남깁니다. 경로 실재, tracked-clean, branch delta,
    # regression 실행 같은 사실 검사는 그대로 유지합니다.
    return (
        "warning: harness_fix에 deterministic enforcement gate가 없습니다. 산문만으로 "
        "원인이 없어지는지 다시 보고, 게이트 없이 닫는다면 근거를 남기세요.",
    )


def run_regression_commands(worktree: Path, commands: list[str]) -> list[dict[str, object]]:
    """Regression command를 직접 실행하고 exact-head receipt를 만듭니다.

    Args:
        worktree: Command를 실행할 repository worktree입니다.
        commands: Shell expansion 없이 실행할 command 문자열 목록입니다.

    Returns:
        Command, exit code, head SHA, timestamp, output hash receipt 목록입니다.

    Raises:
        HarnessIncidentValidationError: Command가 비었거나 실행에 실패할 때 발생합니다.
    """
    command_values = _require_nonempty_strings(list(commands), "regression_command")
    head_sha = _current_head_sha(worktree)
    try:
        readback = RepositoryWorktreeReadback(worktree)
        stable_fingerprint = readback.worktree_fingerprint()
    except RepositoryReadbackError as error:
        raise HarnessIncidentValidationError(
            "cannot read repository bytes before regression command"
        ) from error
    receipts: list[dict[str, object]] = []
    for command in command_values:
        execution_error: HarnessIncidentValidationError | None = None
        result: subprocess.CompletedProcess[bytes] | None = None
        output_hash = ""
        try:
            result, output_hash = _execute_regression_command(worktree, command)
        except HarnessIncidentValidationError as error:
            execution_error = error
        try:
            current_fingerprint = readback.worktree_fingerprint()
        except RepositoryReadbackError as error:
            raise HarnessIncidentValidationError(
                "cannot read repository bytes after regression command"
            ) from error
        if current_fingerprint != stable_fingerprint:
            raise HarnessIncidentValidationError(
                "regression command changed current repository bytes or index during "
                f"verification: {command}"
            ) from execution_error
        if execution_error is not None:
            raise execution_error
        assert result is not None
        if _current_head_sha(worktree) != head_sha:
            raise HarnessIncidentValidationError(
                f"regression command changed current head during verification: {command}"
            )
        receipts.append({
            "command": command,
            "exit_code": result.returncode,
            "head_sha": head_sha,
            "verified_at": datetime.now(UTC).isoformat(),
            "output_sha256": output_hash,
        })
    return receipts


def validate_harness_incidents(
    current_state: object,
    worktree: Path,
    *,
    state: Mapping[str, object] | None = None,
) -> None:
    """이미 runtime-bound로 읽은 state의 incident가 terminal complete인지 검증합니다.

    Args:
        current_state: StateHandle이 읽은 ProcessState, incident projection, 또는 legacy
            pure skill-state object입니다. Path selector는 허용하지 않습니다.
        worktree: Process-ticket이 소유한 worktree 경로입니다.
        state: Phase runner migration 동안 current skill-state를 명시하는 pure value입니다.

    Raises:
        HarnessIncidentValidationError: State shape가 invalid하거나 open/incomplete incident가
            있을 때 발생합니다.
    """
    selected_state = state if state is not None else current_state
    items: tuple[object, ...]
    if isinstance(selected_state, ProcessState):
        items = tuple(selected_state.incidents.values())
    elif isinstance(selected_state, Mapping):
        legacy_incidents = selected_state.get("harness_incidents")
        standard_incidents = selected_state.get("incidents")
        if isinstance(legacy_incidents, list):
            items = tuple(legacy_incidents)
        elif isinstance(standard_incidents, Mapping):
            items = tuple(standard_incidents.values())
        elif all(isinstance(item, HarnessIncidentRecord) for item in selected_state.values()):
            items = tuple(selected_state.values())
        else:
            raise HarnessIncidentValidationError("incident projection must be an object")
    else:
        raise HarnessIncidentValidationError("incident state must be runtime-bound data")
    for raw_item in items:
        item = raw_item.to_payload() if isinstance(raw_item, HarnessIncidentRecord) else raw_item
        if isinstance(item, dict) and item.get("status") == "escalated":
            if not _complete_escalated_shape(item):
                raise HarnessIncidentValidationError(
                    "incomplete escalated harness incident "
                    f"{_incident_display_id(item)} lacks a handoff summary or "
                    "reproduction commands for the loop owner"
                )
            continue
        if not isinstance(item, dict) or item.get("status") != "resolved":
            incident_id = _incident_display_id(item)
            raise HarnessIncidentValidationError(
                "unresolved harness incident "
                f"{incident_id} requires root-cause harness correction or a "
                "loop-owner escalation before Stop"
            )
        incident_id = _incident_display_id(item)
        if not _complete_resolved_shape(item):
            raise HarnessIncidentValidationError(
                "incomplete resolved harness incident "
                f"{incident_id} lacks root cause, durable fix, or regression evidence"
            )
        try:
            validate_resolution_evidence(
                worktree,
                _object_list(item.get("harness_fix")),
                _object_list(item.get("regression_evidence")),
                replay_commands=False,
                require_current_branch_change=False,
            )
        except HarnessIncidentValidationError as exc:
            if str(exc).startswith("harness_fix"):
                raise HarnessIncidentValidationError(
                    "resolved harness incident "
                    f"{incident_id} has a missing, dirty, or unrecorded harness_fix path"
                ) from exc
            raise HarnessIncidentValidationError(
                "incomplete resolved harness incident "
                f"{incident_id} lacks root cause, durable fix, or regression evidence"
            ) from exc


def _require_nonempty_strings(values: list[object], label: str) -> list[str]:
    """Evidence list를 non-empty string 목록으로 좁힙니다.

    Args:
        values: 검증할 runtime list입니다.
        label: 오류에 표시할 field 이름입니다.

    Returns:
        검증된 string 목록입니다.

    Raises:
        HarnessIncidentValidationError: 목록이나 원소가 비었을 때 발생합니다.
    """
    if not values or any(not isinstance(value, str) or not value.strip() for value in values):
        raise HarnessIncidentValidationError(f"{label} must contain non-empty strings")
    return [value for value in values if isinstance(value, str)]


def _validate_regression_receipts(
    worktree: Path,
    harness_fix: list[str],
    evidence: list[object],
    *,
    replay_commands: bool,
) -> None:
    """Stored receipt가 현재 fix content에 적용 가능한 성공 evidence인지 검증합니다.

    Args:
        worktree: Receipt head를 비교할 repository worktree입니다.
        harness_fix: Receipt 이후 변경 여부를 확인할 deterministic fix 경로입니다.
        evidence: 검증할 structured receipt 목록입니다.
        replay_commands: Receipt command를 현재 head에서 재실행할지 여부입니다.

    Raises:
        HarnessIncidentValidationError: Receipt가 비었거나 current head와 다를 때 발생합니다.
    """
    if not evidence:
        raise HarnessIncidentValidationError("regression_evidence must contain receipts")
    current_head = _current_head_sha(worktree)
    for receipt in evidence:
        if not isinstance(receipt, dict):
            raise HarnessIncidentValidationError(
                "regression_evidence must contain structured command receipts"
            )
        command = receipt.get("command")
        exit_code = receipt.get("exit_code")
        head_sha = receipt.get("head_sha")
        verified_at = receipt.get("verified_at")
        output_sha256 = receipt.get("output_sha256")
        if (
            not _nonblank_string(command)
            or not isinstance(exit_code, int)
            or isinstance(exit_code, bool)
            or exit_code != 0
            or not isinstance(head_sha, str)
            or re.fullmatch(r"[0-9a-f]{40}", head_sha) is None
            or not _timezone_aware_timestamp(verified_at)
            or not isinstance(output_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", output_sha256) is None
        ):
            raise HarnessIncidentValidationError(
                "regression_evidence receipt must prove committed exit 0 execution"
            )
        _allowed_regression_arguments(str(command))
        _validate_receipt_fix_ancestry(
            worktree,
            receipt_head=head_sha,
            current_head=current_head,
            harness_fix=harness_fix,
        )
        if replay_commands:
            _execute_regression_command(worktree, str(command))
            if _current_head_sha(worktree) != current_head:
                raise HarnessIncidentValidationError(
                    "regression_evidence replay changed the current exact head"
                )


def _validate_receipt_fix_ancestry(
    worktree: Path,
    *,
    receipt_head: str,
    current_head: str,
    harness_fix: list[str],
) -> None:
    """Receipt commit이 ancestor이고 이후 fix path가 그대로인지 검증합니다.

    Args:
        worktree: Git repository worktree입니다.
        receipt_head: Regression command가 성공한 commit SHA입니다.
        current_head: 현재 branch HEAD SHA입니다.
        harness_fix: Incident를 교정한 repository-relative path입니다.

    Raises:
        HarnessIncidentValidationError: Receipt가 현재 history에 없거나 fix가 바뀌었을 때 발생합니다.
    """
    if receipt_head == current_head:
        return
    environment = _isolated_git_environment()
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", receipt_head, current_head],
        cwd=worktree,
        env=environment,
        capture_output=True,
        check=False,
    )
    if ancestor.returncode != 0:
        raise HarnessIncidentValidationError(
            "regression receipt head is not an ancestor of the current head"
        )
    unchanged = subprocess.run(
        ["git", "diff", "--quiet", receipt_head, current_head, "--", *harness_fix],
        cwd=worktree,
        env=environment,
        capture_output=True,
        check=False,
    )
    if unchanged.returncode == 1:
        raise HarnessIncidentValidationError(
            "harness fix path changed after regression receipt; refresh is required"
        )
    if unchanged.returncode != 0:
        raise HarnessIncidentValidationError(
            "cannot compare harness fix paths with regression receipt head"
        )


def _execute_regression_command(
    worktree: Path,
    command: str,
    *,
    timeout_seconds: float = 1800,
) -> tuple[subprocess.CompletedProcess[bytes], str]:
    """Allowlisted command를 실행하고 stdout/stderr digest를 반환합니다.

    Args:
        worktree: Command를 실행할 repository worktree입니다.
        command: Shell expansion 없는 allowlisted command입니다.

    Returns:
        Completed process와 stdout/NUL/stderr SHA-256입니다.

    Raises:
        HarnessIncidentValidationError: Command를 실행할 수 없거나 exit code가 0이 아닐 때 발생합니다.
    """
    arguments = _allowed_regression_arguments(command)
    directory = worktree
    expected_output = None
    nodes = ()
    environment = _isolated_git_environment()
    if arguments[:2] == [".neurath/run", "verify"]:
        from neurath.runtime.commands import bound_command
        try:
            nodes = tuple(arguments[4::2])
            arguments, directory, configured_timeout, expected_output = bound_command(worktree, arguments[2], nodes)
            timeout_seconds = min(timeout_seconds, configured_timeout)
            environment.pop("PYTEST_ADDOPTS", None)
            environment.pop("PYTEST_CURRENT_TEST", None)
            _reject_nonexecuting_arguments(arguments, command)
        except (ValueError, OSError, TypeError, KeyError) as error:
            raise HarnessIncidentValidationError(str(error)) from error
    try:
        bounded = run_bounded_process(
            arguments,
            cwd=directory,
            environment=environment,
            timeout_seconds=timeout_seconds,
        )
    except OSError as exc:
        raise HarnessIncidentValidationError(
            f"regression command could not run: {command}"
        ) from exc
    result = subprocess.CompletedProcess(
        args=arguments,
        returncode=bounded.returncode,
        stdout=bounded.stdout,
        stderr=bounded.stderr,
    )
    combined_output = result.stdout + b"\0" + result.stderr
    output_hash = hashlib.sha256(combined_output).hexdigest()
    if bounded.timed_out:
        raise HarnessRegressionExecutionError(
            command,
            result.returncode,
            _bounded_diagnostic_tail(
                result.stdout + b"\n" + result.stderr + b"\nregression command timed out"
            ),
            output_hash,
        )
    if result.returncode != 0:
        raise HarnessRegressionExecutionError(
            command,
            result.returncode,
            _bounded_diagnostic_tail(result.stdout + b"\n" + result.stderr),
            output_hash,
        )
    if expected_output is not None and expected_output.encode() not in result.stdout:
        raise HarnessIncidentValidationError("configured stdout requirement was not satisfied")
    if nodes:
        output = result.stdout.decode("utf-8", errors="replace")
        for node in nodes:
            # A passing aggregate cannot substitute for any requested leaf node.
            if not re.search(r"(?m)^" + re.escape(node) + r" PASSED(?:\s|$)", output):
                raise HarnessIncidentValidationError(f"requested pytest node did not pass: {node}")
    _require_effective_regression_result(arguments, result, command)
    return result, output_hash


def _bounded_diagnostic_tail(output: bytes) -> str:
    """Terminal 진단에 필요한 output tail만 ANSI control 없이 반환합니다."""
    decoded = output.decode("utf-8", errors="replace")
    sanitized = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", decoded)
    return sanitized[-8192:]


def _current_head_sha(worktree: Path) -> str:
    """Worktree의 current Git head SHA를 읽습니다.

    Args:
        worktree: Git worktree 경로입니다.

    Returns:
        40자리 current commit SHA입니다.

    Raises:
        HarnessIncidentValidationError: Git head를 읽을 수 없을 때 발생합니다.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=worktree,
            env=_isolated_git_environment(),
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise HarnessIncidentValidationError("cannot read regression evidence head SHA") from exc
    head_sha = result.stdout.strip()
    if result.returncode != 0 or re.fullmatch(r"[0-9a-f]{40}", head_sha) is None:
        raise HarnessIncidentValidationError("cannot read regression evidence head SHA")
    return head_sha


def _changed_paths(worktree: Path) -> set[str]:
    """Current branch에서 committed change인 repository path를 수집합니다.

    Args:
        worktree: Git worktree 경로입니다.

    Returns:
        Base branch/parent 이후 committed changed path 집합입니다.

    Raises:
        HarnessIncidentValidationError: 비교 가능한 Git base를 찾지 못할 때 발생합니다.
    """
    changed: set[str] = set()
    base_found = False
    environment = _isolated_git_environment()
    remote_head = subprocess.run(
        ["git", "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD"],
        cwd=worktree, env=environment, capture_output=True, text=True, check=False,
    ).stdout.strip()
    for base in (remote_head, "HEAD^"):
        if not base:
            continue
        exists = subprocess.run(
            ["git", "rev-parse", "--verify", base],
            cwd=worktree,
            env=environment,
            capture_output=True,
            check=False,
        )
        if exists.returncode != 0:
            continue
        diff = subprocess.run(
            ["git", "diff", "--name-only", f"{base}...HEAD"],
            cwd=worktree,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        if diff.returncode == 0:
            changed.update(line for line in diff.stdout.splitlines() if line)
            base_found = True
            break
    if not base_found and not changed:
        raise HarnessIncidentValidationError(
            "harness_fix cannot be verified against a committed branch base"
        )
    return changed


def _is_tracked_clean_path(worktree: Path, path: Path) -> bool:
    """Harness fix가 tracked이고 index/worktree에서 clean인지 확인합니다.

    Args:
        worktree: Git worktree 경로입니다.
        path: Repository-relative harness fix 경로입니다.

    Returns:
        Current head가 추적하고 staged/unstaged diff가 없으면 true입니다.
    """
    relative = path.as_posix()
    environment = _isolated_git_environment()
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", relative],
        cwd=worktree,
        env=environment,
        capture_output=True,
        check=False,
    )
    if tracked.returncode != 0:
        return False
    for arguments in (
        ["git", "diff", "--quiet", "--", relative],
        ["git", "diff", "--cached", "--quiet", "--", relative],
    ):
        if (
            subprocess.run(
                arguments,
                cwd=worktree,
                env=environment,
                check=False,
            ).returncode
            != 0
        ):
            return False
    return True


def _isolated_git_environment() -> dict[str, str]:
    """Caller hook의 repository/import/actor authority가 verifier를 덮지 않게 합니다.

    Returns:
        PATH 등 일반 환경은 보존하고 repository-scoped Git/pre-commit/Python import와
        foreground runtime identity 변수를 제거한 환경입니다.
    """
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("GIT_", "NEURATH_AGENT_"))
        and key
        not in {
            "CLAUDE_CODE_SESSION_ID",
            "CODEX_THREAD_ID",
            "PRE_COMMIT",
            "PYTHONPATH",
        }
    }
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return environment


def _allowed_regression_arguments(command: str) -> list[str]:
    """Shell expansion 없는 allowlisted regression command argv를 반환합니다.

    Args:
        command: CLI가 실행하거나 receipt에서 재검증할 command 문자열입니다.

    Returns:
        실행 가능한 argv 목록입니다.

    Raises:
        HarnessIncidentValidationError: Command가 allowlisted test/check가 아닐 때 발생합니다.
    """
    try:
        arguments = shlex.split(command)
    except ValueError as exc:
        raise HarnessIncidentValidationError(
            f"regression command is not valid shell-free argv: {command}"
        ) from exc
    if not arguments:
        raise HarnessIncidentValidationError("regression_command must be non-empty")
    _reject_nonexecuting_arguments(arguments, command)
    if arguments[:2] == [".neurath/run", "verify"]:
        if len(arguments) < 3 or re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", arguments[2]) is None:
            raise HarnessIncidentValidationError("invalid project verification binding")
        tail = arguments[3:]
        if len(tail) % 2 or any(value != "--node" for value in tail[::2]):
            raise HarnessIncidentValidationError("only exact --node arguments are allowed")
        if tail:
            from scripts.agent_harness.verification_runner import VerificationKind, VerificationRequest
            if arguments[2] != "pytest":
                raise HarnessIncidentValidationError("only pytest accepts nodes")
            VerificationRequest(VerificationKind.PYTEST, tuple(tail[1::2]))
        return arguments
    if arguments[:3] == ["uv", "run", "pre-commit"] and arguments[3:4] == ["run"]:
        if arguments != ["uv", "run", "pre-commit", "run", "--all-files"]:
            raise HarnessIncidentValidationError(
                "pre-commit regression command must be exactly "
                f"`uv run pre-commit run --all-files`: {command}"
            )
        return arguments
    if arguments[:2] == ["mise", "run"]:
        if arguments != ["mise", "run", "check"]:
            raise HarnessIncidentValidationError(
                f"mise regression command must be exact `mise run check`: {command}"
            )
        return arguments
    if arguments[:2] == ["uv", "run"] and arguments[2:3] == ["pytest"]:
        return arguments
    if arguments[:3] == ["uv", "run", "python"]:
        _validate_python_regression(arguments[3:], command)
        return arguments
    if Path(arguments[0]).name.startswith("python"):
        _validate_python_regression(arguments[1:], command)
        return arguments
    raise HarnessIncidentValidationError(
        f"regression command is not an allowlisted test/check entrypoint: {command}"
    )


def _validate_python_regression(arguments: list[str], command: str) -> None:
    """Python invocation이 test 또는 repository check module/script인지 검증합니다.

    Args:
        arguments: Python executable 뒤 argv입니다.
        command: 오류에 표시할 original command입니다.

    Raises:
        HarnessIncidentValidationError: Python invocation이 임의 code 실행일 때 발생합니다.
    """
    if arguments[:1] == ["-m"] and len(arguments) >= 2:
        module = arguments[1]
        if module in {"pytest", "unittest"} or module in ALLOWED_REGRESSION_MODULES:
            return
    raise HarnessIncidentValidationError(
        f"regression command is not an allowlisted Python test/check: {command}"
    )


def _reject_nonexecuting_arguments(arguments: list[str], command: str) -> None:
    """Help/version/collection-only invocation을 regression 실행으로 위장하지 못하게 합니다.

    Args:
        arguments: 검증할 전체 command argv입니다.
        command: 오류에 표시할 original command입니다.

    Raises:
        HarnessIncidentValidationError: 실행 없는 정보 출력 option이 포함될 때 발생합니다.
    """
    rejected = NONEXECUTING_REGRESSION_ARGUMENTS.intersection(arguments)
    if rejected:
        raise HarnessIncidentValidationError(
            "regression command must execute checks instead of displaying or collecting them: "
            f"{command}"
        )


def _require_effective_regression_result(
    arguments: list[str],
    result: subprocess.CompletedProcess[bytes],
    command: str,
) -> None:
    """Test runner receipt가 실제 test 1개 이상을 실행했는지 검증합니다.

    Args:
        arguments: 실행한 전체 command argv입니다.
        result: Exit 0 subprocess 결과입니다.
        command: 오류에 표시할 original command입니다.

    Raises:
        HarnessIncidentValidationError: Test runner가 test를 하나도 실행하지 않았을 때 발생합니다.
    """
    runner = _test_runner(arguments)
    if runner is None:
        return
    output = (result.stdout + b"\n" + result.stderr).decode("utf-8", errors="replace")
    # skip/xfail은 test 본문을 실행하지 않으므로 전부-skip 실행은 no-op receipt가 된다.
    # incident resolution은 실제로 통과한 test 1개 이상을 증명해야 하며 skip만으로 닫지 못한다.
    if runner == "unittest":
        ran_match = re.search(r"Ran\s+(\d+)\s+tests?", output)
        ran = int(ran_match.group(1)) if ran_match is not None else 0
        non_executing = sum(
            int(value)
            for pattern in (r"skipped=(\d+)", r"expected failures=(\d+)")
            for value in re.findall(pattern, output)
        )
        executed = ran - non_executing
    else:
        executed = sum(
            int(value) for value in re.findall(r"(?:^|[\s,])(\d+)\s+passed(?=[\s,]|$)", output)
        )
    if executed < 1:
        raise HarnessIncidentValidationError(f"regression command executed zero tests: {command}")


def _test_runner(arguments: list[str]) -> str | None:
    """Command argv에서 supported test runner를 식별합니다.

    Args:
        arguments: 실행한 전체 command argv입니다.

    Returns:
        `pytest`, `unittest`, 또는 repository checker이면 None입니다.
    """
    if arguments[:3] == ["uv", "run", "pytest"] or Path(arguments[0]).name == "pytest":
        return "pytest"
    for index, value in enumerate(arguments[:-1]):
        if value == "-m" and arguments[index + 1] in {"pytest", "unittest"}:
            return arguments[index + 1]
    return None


def _timezone_aware_timestamp(value: object) -> bool:
    """Receipt timestamp가 timezone-aware ISO-8601인지 확인합니다.

    Args:
        value: Runtime timestamp value입니다.

    Returns:
        Offset을 가진 ISO-8601 string이면 true입니다.
    """
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _is_deterministic_gate_path(path: Path) -> bool:
    """Repo-relative path가 executable harness 위치를 가리키는지 분류합니다.

    Args:
        path: 검증할 repository-relative path입니다.

    Returns:
        Hook, script, pre-commit gate, 또는 기계 검사 skill 계약(contracts.json)
        경로이면 true입니다. Prose rule·skill 문서는 결정적 gate가 아닙니다.
    """
    parts = path.parts
    executable_suffix = path.suffix in {".py", ".sh"}
    return (
        path.name == ".pre-commit-config.yaml"
        or path.as_posix() == ".agents/skills/contracts.json"
        or (executable_suffix and parts[:1] == ("scripts",))
        or (executable_suffix and parts[:2] == (".codex", "hooks"))
        or (executable_suffix and parts[:2] == (".agents", "skills") and "scripts" in parts[3:])
    )


def _complete_resolved_shape(incident: dict[str, object]) -> bool:
    """Resolved incident의 stable/occurrence identity와 필수 field shape를 검사합니다.

    Args:
        incident: 검증할 resolved incident object입니다.

    Returns:
        모든 필수 scalar/list field가 non-empty이면 true입니다.
    """
    scalar_fields = (
        "id",
        "rule_id",
        "occurrence_id",
        "symptom",
        "root_cause",
        "recorded_at",
        "resolved_at",
    )
    return all(_nonblank_string(incident.get(field)) for field in scalar_fields) and all(
        isinstance(incident.get(field), list) and bool(incident.get(field))
        for field in ("harness_fix", "regression_evidence")
    )


def _complete_escalated_shape(incident: dict[str, object]) -> bool:
    """Escalated incident의 identity와 loop-owner handoff evidence shape를 검사합니다.

    Args:
        incident: 검증할 escalated incident object입니다.

    Returns:
        Identity, timestamp, 이관 요약, 재현 command가 모두 채워져 있으면 true입니다.
    """
    scalar_fields = ("id", "rule_id", "occurrence_id", "symptom", "recorded_at", "escalated_at")
    if not all(_nonblank_string(incident.get(field)) for field in scalar_fields):
        return False
    escalation = incident.get("escalation")
    if not isinstance(escalation, dict):
        return False
    if escalation.get("handoff_route") != "loop-owner":
        return False
    if not _nonblank_string(escalation.get("summary")):
        return False
    reproduction_commands = escalation.get("reproduction_commands")
    return (
        isinstance(reproduction_commands, list)
        and bool(reproduction_commands)
        and all(_nonblank_string(command) for command in reproduction_commands)
    )


def _nonblank_string(value: object) -> bool:
    """Runtime value가 공백이 아닌 문자열인지 확인합니다.

    Args:
        value: 검사할 runtime value입니다.

    Returns:
        Non-empty string이면 true입니다.
    """
    return isinstance(value, str) and bool(value.strip())


def _incident_display_id(item: object) -> str:
    """Incident 오류에 표시할 occurrence 또는 stable identity를 반환합니다.

    Args:
        item: Incident ledger 원소입니다.

    Returns:
        표시 가능한 identity가 없으면 `unknown`입니다.
    """
    if not isinstance(item, dict):
        return "unknown"
    for field in ("rule_id", "occurrence_id", "id"):
        value = item.get(field)
        if _nonblank_string(value):
            return str(value)
    return "unknown"


def _object_list(value: object) -> list[object]:
    """Runtime value를 object list로 좁히고 아니면 빈 list를 반환합니다.

    Args:
        value: 변환할 runtime value입니다.

    Returns:
        List value 또는 빈 list입니다.
    """
    return value if isinstance(value, list) else []


def main() -> int:
    """Runtime identity로 exact session을 선택해 incident lifecycle command를 실행합니다.

    Returns:
        Mutation 또는 validation 성공은 0, typed contract 실패는 2입니다.
    """
    parser = argparse.ArgumentParser(description="Manage runtime-bound session harness incidents.")
    commands = parser.add_subparsers(dest="command", required=True)
    record = commands.add_parser("record")
    record.add_argument("--id", required=True)
    record.add_argument("--symptom", required=True)
    resolve = commands.add_parser("resolve")
    resolve.add_argument("--id", required=True)
    resolve.add_argument("--root-cause", required=True)
    resolve.add_argument("--harness-fix", action="append", required=True)
    resolve.add_argument("--regression-command", action="append", required=True)
    escalate = commands.add_parser("escalate")
    escalate.add_argument("--id", required=True)
    escalate.add_argument("--summary", required=True)
    escalate.add_argument("--reproduction-command", action="append", required=True)
    refresh = commands.add_parser("refresh")
    refresh.add_argument("--id", action="append", required=True)
    refresh.add_argument("--regression-command", action="append")
    supersede = commands.add_parser("supersede")
    supersede.add_argument("--id", required=True)
    supersede.add_argument("--harness-fix", action="append", required=True)
    supersede.add_argument("--regression-command", action="append", required=True)
    commands.add_parser("validate")
    args = parser.parse_args()
    try:
        worktree = Path.cwd().resolve()
        binding = RuntimeEnvironmentResolver().resolve(os.environ)
        handle = StateHandle.attach(SessionLocator.from_worktree(worktree), binding)
        application = HarnessIncidentApplication(handle, worktree)
        output: object
        if args.command == "record":
            output = application.record(args.id, args.symptom).to_payload()
        elif args.command == "resolve":
            output = application.resolve(
                args.id,
                args.root_cause,
                args.harness_fix,
                args.regression_command,
            ).to_payload()
        elif args.command == "escalate":
            output = application.escalate(
                args.id,
                args.summary,
                args.reproduction_command,
            ).to_payload()
        elif args.command == "refresh":
            refreshed = application.refresh(args.id, args.regression_command)
            payloads = [incident.to_payload() for incident in refreshed]
            output = payloads[0] if len(payloads) == 1 else {"refreshed": payloads}
        elif args.command == "supersede":
            output = application.supersede(
                args.id,
                args.harness_fix,
                args.regression_command,
            ).to_payload()
        else:
            validate_harness_incidents(handle.inspect(), worktree)
            output = {"status": "valid"}
        for warning in application.warnings:
            print(warning, file=sys.stderr)
    except (
        HarnessIncidentValidationError,
        RuntimeIdentityError,
        SessionKernelError,
        TypeError,
        ValueError,
        OSError,
    ) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

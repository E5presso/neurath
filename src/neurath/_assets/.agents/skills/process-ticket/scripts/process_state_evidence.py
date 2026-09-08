"""Process-ticket evidence를 exact session workflow에 optimistic commit합니다.

Stop 게이트가 신뢰하는 `merged`와 `monitor_event_subscription`은 자유
JSON이 아니라 GitHub 또는 live monitor read-back을 통과해야 저장됩니다.
"""

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import NoReturn

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))
MONITOR_RUNTIME_SCRIPTS = REPOSITORY_ROOT / ".agents/skills/monitor-pr/scripts"
if str(MONITOR_RUNTIME_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(MONITOR_RUNTIME_SCRIPTS))

from monitor_observation_store import MonitorObservationStore
from monitor_runtime_resources import MonitorRuntimeResources

from scripts.agent_harness.session_kernel import (
    SessionKernelError,
    SessionLocator,
    WorkflowId,
)
from scripts.agent_harness.skill_state_store import (
    SkillStateConflict,
    SkillStateSnapshot,
    SkillStateStore,
)
from scripts.agent_harness.state_handle import (
    RuntimeEnvironmentResolver,
    RuntimeIdentityError,
    StateHandle,
)


class ProcessStateEvidenceError(RuntimeError):
    """Evidence application이 caller에게 안전하게 노출할 base error입니다."""


class ProcessStateEvidenceInputError(ProcessStateEvidenceError):
    """CLI argument 또는 JSON value가 public contract를 위반했습니다."""


class ProcessStateEvidenceValidationError(ProcessStateEvidenceError):
    """Evidence field 또는 external read-back이 신뢰 계약을 위반했습니다."""


class ProcessStateEvidenceConflict(ProcessStateEvidenceError):
    """External read-back이 결속된 workflow revision이 더는 current가 아닙니다."""


class ProcessStateEvidenceResult:
    """CLI process status와 stdout, stderr를 immutable result로 결합합니다."""

    __slots__ = ("exit_code", "stderr", "stdout")

    def __init__(self, *, exit_code: int, stdout: str, stderr: str) -> None:
        """Process adapter가 그대로 출력할 결과를 고정합니다.

        Args:
            exit_code: 성공은 0, input/state 오류는 2입니다.
            stdout: 성공한 evidence JSON object입니다.
            stderr: 실패의 구체적인 fail-closed 설명입니다.
        """
        object.__setattr__(self, "exit_code", exit_code)
        object.__setattr__(self, "stdout", stdout)
        object.__setattr__(self, "stderr", stderr)

    exit_code: int
    """Caller에게 반환할 process status입니다."""

    stdout: str
    """성공 결과를 담은 JSON object입니다."""

    stderr: str
    """실패 이유를 담은 단일 message입니다."""

    def __setattr__(self, name: str, value: object) -> None:
        """생성된 CLI result의 변경을 거부합니다.

        Args:
            name: 변경을 시도한 attribute 이름입니다.
            value: Attribute에 새로 대입하려는 값입니다.

        Raises:
            AttributeError: CLI result는 생성 뒤 immutable입니다.
        """
        raise AttributeError(f"{type(self).__name__} is immutable")


class ProcessStateEvidenceArgumentParser(argparse.ArgumentParser):
    """Argparse의 process exit을 application input error로 변환합니다."""

    def error(self, message: str) -> NoReturn:
        """Argument 위반을 typed application error로 올립니다.

        Args:
            message: Argparse가 생성한 구체적인 위반 설명입니다.

        Returns:
            항상 exception을 발생시키므로 정상 반환하지 않습니다.

        Raises:
            ProcessStateEvidenceInputError: 모든 parser error에서 발생합니다.
        """
        raise ProcessStateEvidenceInputError(message)


class EvidenceMutation:
    """검증이 끝난 field/value를 current skill state에 적용하는 pure transform입니다."""

    __slots__ = ("_field", "_updated_at", "_value")

    def __init__(self, *, field: str, value: object, updated_at: str) -> None:
        """External effect가 없는 deterministic replacement input을 고정합니다.

        Args:
            field: Allowlist 검증을 통과한 process-ticket evidence key입니다.
            value: JSON validation 또는 read-back을 마친 current evidence입니다.
            updated_at: Transform 실행 전에 확정한 timezone-aware timestamp입니다.
        """
        self._field = field
        self._value = value
        self._updated_at = updated_at

    def __call__(self, current: Mapping[str, object]) -> Mapping[str, object]:
        """Current object의 모든 unrelated key를 보존하고 evidence를 교체합니다.

        Args:
            current: SkillStateStore가 제공한 read-only latest skill state입니다.

        Returns:
            Evidence와 updated timestamp가 반영된 새 JSON object입니다.
        """
        return MappingProxyType({
            **current,
            self._field: self._value,
            "updated_at": self._updated_at,
        })


class VerifiedMergeMutation:
    """GitHub receipt를 검증할 때 사용한 subscription이 유지된 경우만 merge를 기록합니다."""

    __slots__ = ("_expected_subscription", "_receipt", "_updated_at")

    def __init__(
        self,
        *,
        expected_subscription: Mapping[str, object],
        receipt: Mapping[str, object],
        updated_at: str,
    ) -> None:
        """External read-back의 state prerequisite와 deterministic 결과를 고정합니다.

        Args:
            expected_subscription: GitHub read-back 대상을 결정한 current route입니다.
            receipt: GitHub이 MERGED로 확인한 immutable receipt입니다.
            updated_at: External verification 뒤 확정한 timezone-aware timestamp입니다.
        """
        self._expected_subscription = self._canonical(expected_subscription)
        self._receipt = dict(receipt)
        self._updated_at = updated_at

    def __call__(self, current: Mapping[str, object]) -> Mapping[str, object]:
        """Subscription prerequisite를 재검증하고 merge receipt를 pure transform합니다.

        Args:
            current: Optimistic retry마다 SkillStateStore가 제공하는 latest state입니다.

        Returns:
            Unrelated concurrent update를 보존한 merged evidence object입니다.

        Raises:
            ProcessStateEvidenceValidationError: Verification 이후 subscription이 바뀌면
                stale receipt 적용을 거부합니다.
        """
        subscription = current.get("monitor_event_subscription")
        if not isinstance(subscription, Mapping):
            raise ProcessStateEvidenceValidationError(
                "monitor_event_subscription changed during merge verification"
            )
        if self._canonical(subscription) != self._expected_subscription:
            raise ProcessStateEvidenceValidationError(
                "monitor_event_subscription changed during merge verification"
            )
        return MappingProxyType({
            **current,
            "merged": dict(self._receipt),
            "updated_at": self._updated_at,
        })

    def _canonical(self, value: Mapping[str, object]) -> str:
        try:
            return json.dumps(
                dict(value),
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        except (TypeError, ValueError) as error:
            raise ProcessStateEvidenceValidationError(
                "monitor_event_subscription must be JSON-compatible"
            ) from error


class GitHubMergeVerifier:
    """Registered subscription의 PR을 GitHub CLI로 read-back합니다."""

    def verify(self, subscription: Mapping[str, object]) -> Mapping[str, object]:
        """GitHub이 MERGED로 확인한 PR receipt를 반환합니다.

        Args:
            subscription: Repo와 PR number를 포함한 current registered route입니다.

        Returns:
            Repo, PR, merge timestamp, merge commit이 검증된 receipt입니다.

        Raises:
            ProcessStateEvidenceValidationError: Subscription 또는 GitHub output이
                merge evidence 계약을 만족하지 못하면 발생합니다.
        """
        repo = subscription.get("repo")
        pr_number = subscription.get("pr_number")
        if not isinstance(repo, str) or not repo:
            raise ProcessStateEvidenceValidationError(
                "monitor_event_subscription requires repo for merge read-back"
            )
        if not isinstance(pr_number, int) or isinstance(pr_number, bool) or pr_number <= 0:
            raise ProcessStateEvidenceValidationError(
                "monitor_event_subscription requires positive pr_number for merge read-back"
            )
        try:
            completed = subprocess.run(
                (
                    "gh",
                    "pr",
                    "view",
                    str(pr_number),
                    "--repo",
                    repo,
                    "--json",
                    "state,mergedAt,mergeCommit",
                ),
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as error:
            raise ProcessStateEvidenceValidationError(
                "GitHub merge read-back command is unavailable"
            ) from error
        if completed.returncode != 0:
            raise ProcessStateEvidenceValidationError(
                f"GitHub merge read-back failed: {completed.stderr.strip()}"
            )
        try:
            payload: object = json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            raise ProcessStateEvidenceValidationError(
                "GitHub merge read-back must be valid JSON"
            ) from error
        if not isinstance(payload, dict):
            raise ProcessStateEvidenceValidationError(
                "GitHub merge read-back must return an object"
            )
        merged_at = payload.get("mergedAt")
        if payload.get("state") != "MERGED" or not merged_at:
            raise ProcessStateEvidenceValidationError(
                f"GitHub reports PR #{pr_number} is not merged: state={payload.get('state')!r}"
            )
        merge_commit = payload.get("mergeCommit")
        merge_commit_oid = merge_commit.get("oid") if isinstance(merge_commit, dict) else None
        return MappingProxyType({
            "repo": repo,
            "pr_number": pr_number,
            "state": "MERGED",
            "merged_at": merged_at,
            "merge_commit_oid": merge_commit_oid,
            "verified_at": datetime.now(UTC).isoformat(),
        })


class MonitorSubscriptionValidator:
    """Subscription을 exact session/workflow route와 live monitor state에 결속합니다."""

    _RESUME_ADAPTERS = frozenset({"app-server", "command", "unavailable"})
    _LEGACY_PATH_KEYS = frozenset({
        "process_state_path",
        "state_path",
        "thread_id",
        "worktree",
    })

    def __init__(
        self,
        *,
        resources: MonitorRuntimeResources,
        workflow_id: WorkflowId,
    ) -> None:
        """Runtime-derived resource handle과 workflow identity를 고정합니다.

        Args:
            resources: Session/worktree/private observation을 파생한 opaque handle입니다.
            workflow_id: CLI가 필수 selector로 받은 exact workflow identity입니다.
        """
        self._resources = resources
        self._workflow_id = workflow_id

    def validate_identity(self, value: object) -> Mapping[str, object]:
        """Subscription shape와 session/workflow identity를 fail-closed 검증합니다.

        Args:
            value: CLI 또는 current skill state에서 읽은 subscription입니다.

        Returns:
            Identity, route, opaque observation field가 유효한 subscription입니다.

        Raises:
            ProcessStateEvidenceValidationError: Shape 또는 identity가 잘못되면
                발생합니다.
        """
        if not isinstance(value, Mapping):
            raise ProcessStateEvidenceValidationError(
                "monitor_event_subscription evidence must be an object"
            )
        legacy_keys = self._LEGACY_PATH_KEYS.intersection(value)
        if legacy_keys:
            raise ProcessStateEvidenceValidationError(
                "monitor_event_subscription legacy path selectors are forbidden: "
                + ", ".join(sorted(legacy_keys))
            )
        provider = value.get("provider")
        repo = value.get("repo")
        pr_number = value.get("pr_number")
        session_id = value.get("session_id")
        workflow_id = value.get("workflow_id")
        runtime_id = value.get("runtime_id")
        worktree_id = value.get("worktree_id")
        observation_resource = value.get("observation_resource")
        poll_interval = value.get("poll_interval_seconds")
        resume_adapter = value.get("resume_adapter")
        if provider != "local-pr-monitor":
            raise ProcessStateEvidenceValidationError(
                "monitor_event_subscription provider must be local-pr-monitor"
            )
        if not isinstance(repo, str) or not repo:
            raise ProcessStateEvidenceValidationError("monitor_event_subscription requires repo")
        if not isinstance(pr_number, int) or isinstance(pr_number, bool) or pr_number <= 0:
            raise ProcessStateEvidenceValidationError(
                "monitor_event_subscription requires positive pr_number"
            )
        if session_id != self._resources.session_id:
            raise ProcessStateEvidenceValidationError(
                "monitor_event_subscription session identity does not match runtime"
            )
        if workflow_id != str(self._workflow_id):
            raise ProcessStateEvidenceValidationError(
                "monitor_event_subscription workflow identity does not match selector"
            )
        if not isinstance(runtime_id, str) or not runtime_id.strip():
            raise ProcessStateEvidenceValidationError(
                "monitor_event_subscription requires runtime_id"
            )
        if worktree_id != self._resources.worktree_id:
            raise ProcessStateEvidenceValidationError(
                "monitor_event_subscription worktree identity does not match execution cwd"
            )
        if observation_resource != self._resources.observation_resource():
            raise ProcessStateEvidenceValidationError(
                "monitor_event_subscription observation resource does not match execution cwd"
            )
        if (
            not isinstance(poll_interval, int)
            or isinstance(poll_interval, bool)
            or poll_interval <= 0
        ):
            raise ProcessStateEvidenceValidationError(
                "monitor_event_subscription requires positive poll_interval_seconds"
            )
        if resume_adapter not in self._RESUME_ADAPTERS:
            raise ProcessStateEvidenceValidationError(
                "monitor_event_subscription resume_adapter is not recognized"
            )
        if not isinstance(value.get("last_seen"), Mapping):
            raise ProcessStateEvidenceValidationError(
                "monitor_event_subscription requires last_seen observation baseline"
            )
        pid = value.get("pid")
        if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
            raise ProcessStateEvidenceValidationError(
                "monitor_event_subscription requires a positive monitor pid"
            )
        heartbeat = value.get("heartbeat_at_epoch")
        if not isinstance(heartbeat, int | float) or isinstance(heartbeat, bool):
            raise ProcessStateEvidenceValidationError(
                "monitor_event_subscription requires heartbeat_at_epoch"
            )
        if any(not isinstance(key, str) for key in value):
            raise ProcessStateEvidenceValidationError(
                "monitor_event_subscription keys must be strings"
            )
        return MappingProxyType(dict(value))

    def validate_live(self, value: object) -> Mapping[str, object]:
        """Runtime-derived private observation cache와 process 생존을 검증합니다.

        Args:
            value: Exact route validation을 먼저 통과할 subscription입니다.

        Returns:
            Live runtime identity와 일치하는 read-only subscription입니다.

        Raises:
            ProcessStateEvidenceValidationError: Runtime state가 없거나 identity,
                heartbeat, process 생존 검증이 실패하면 발생합니다.
        """
        subscription = self.validate_identity(value)
        try:
            raw_state = MonitorObservationStore(self._resources.observation_path).read()
        except (OSError, TypeError, json.JSONDecodeError) as error:
            raise ProcessStateEvidenceValidationError(
                "monitor runtime state is not readable"
            ) from error
        expected = {
            "provider": subscription["provider"],
            "repo": subscription["repo"],
            "pr_number": subscription["pr_number"],
            "session_id": subscription["session_id"],
            "workflow_id": subscription["workflow_id"],
            "runtime_id": subscription["runtime_id"],
            "worktree_id": subscription["worktree_id"],
            "resume_adapter": subscription["resume_adapter"],
        }
        for field, expected_value in expected.items():
            if raw_state.get(field) != expected_value:
                raise ProcessStateEvidenceValidationError(
                    f"monitor runtime {field} mismatch: "
                    f"expected {expected_value!r}, got {raw_state.get(field)!r}"
                )
        pid = raw_state.get("pid")
        if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
            raise ProcessStateEvidenceValidationError("monitor runtime pid is missing")
        heartbeat = raw_state.get("heartbeat_at_epoch")
        if not isinstance(heartbeat, int | float) or isinstance(heartbeat, bool):
            raise ProcessStateEvidenceValidationError("monitor runtime heartbeat is missing")
        if pid != subscription["pid"]:
            raise ProcessStateEvidenceValidationError(
                "monitor runtime pid no longer matches the read-back receipt"
            )
        receipt_heartbeat = subscription["heartbeat_at_epoch"]
        if not isinstance(receipt_heartbeat, int | float) or isinstance(
            receipt_heartbeat,
            bool,
        ):
            raise ProcessStateEvidenceValidationError(
                "monitor read-back receipt heartbeat is invalid"
            )
        if float(heartbeat) < float(receipt_heartbeat):
            raise ProcessStateEvidenceValidationError(
                "monitor runtime heartbeat regressed from the read-back receipt"
            )
        last_seen = raw_state.get("last_observed")
        if not isinstance(last_seen, dict):
            last_seen = raw_state.get("last_seen")
        if not isinstance(last_seen, dict):
            raise ProcessStateEvidenceValidationError(
                "monitor runtime observation baseline is missing"
            )
        try:
            os.kill(pid, 0)
        except (OSError, ValueError) as error:
            raise ProcessStateEvidenceValidationError(
                "monitor runtime process is not alive"
            ) from error
        return subscription


class ProcessStateEvidenceApplication:
    """Cwd, runtime identity, workflow ID로 evidence transaction을 exact resolve합니다."""

    _ALLOWED_FIELDS = frozenset({
        "commit_done",
        "failed",
        "merged",
        "monitor_event_subscription",
        "monitor_started",
        "pr_opened",
        "push_done",
    })

    def __init__(self) -> None:
        """Runtime resolver와 external receipt verifier를 application에 귀속시킵니다."""
        self._resolver = RuntimeEnvironmentResolver()
        self._merge_verifier = GitHubMergeVerifier()

    def run(
        self,
        arguments: Sequence[str],
        environment: Mapping[str, object],
        cwd: Path,
    ) -> ProcessStateEvidenceResult:
        """One evidence command를 exact workflow-local CAS로 적용합니다.

        Args:
            arguments: Workflow identity, evidence field, JSON value를 담은 arguments입니다.
            environment: Vendor runtime이 소유한 session/actor identity입니다.
            cwd: Git common control root와 monitor worktree를 해석할 실행 경로입니다.

        Returns:
            성공 JSON 또는 fail-closed stderr와 process code를 담은 결과입니다.

        Raises:
            ProcessStateEvidenceConflict: External evidence read-back 중 workflow가 바뀌면
                내부 fail-closed result로 변환되기 전에 발생합니다.
        """
        try:
            namespace = self._parser().parse_args(tuple(arguments))
            workflow_id = WorkflowId(self._text(namespace, "workflow_id"))
            field = self._allowed_field(namespace)
            value = self._json_value(self._text(namespace, "value_json"))
            locator = SessionLocator.from_worktree(cwd)
            binding = self._resolver.resolve(environment)
            handle = StateHandle.attach(locator, binding)
            resources = MonitorRuntimeResources.resolve(cwd=cwd, environment=environment)
            return self.apply_bound(handle=handle, workflow_id=workflow_id, resources=resources, field=field, value=value)
        except (
            ProcessStateEvidenceError,
            RuntimeIdentityError,
            SessionKernelError,
        ) as error:
            return ProcessStateEvidenceResult(
                exit_code=2,
                stdout="",
                stderr=str(error),
            )
        except subprocess.CalledProcessError as error:
            return ProcessStateEvidenceResult(
                exit_code=2,
                stdout="",
                stderr=f"repository identity is unavailable: {error}",
            )

    def apply_bound(
        self, *, handle: StateHandle, workflow_id: WorkflowId,
        resources: MonitorRuntimeResources, field: str, value: object,
    ) -> ProcessStateEvidenceResult:
        """Apply typed evidence using a caller authenticated by the CLI or MCP adapter.

        Args:
            handle: Actual native caller state handle.
            workflow_id: Exact workflow owning the evidence.
            resources: Resources derived from the same native caller and worktree.
            field: Existing allowlisted evidence field.
            value: Structured event result, still subject to live domain checks.

        Returns:
            Existing structured success receipt.

        Raises:
            ProcessStateEvidenceInputError: The field is not part of the existing contract.
        """
        if field not in self._ALLOWED_FIELDS:
            raise ProcessStateEvidenceInputError("unsupported evidence field")
        store = SkillStateStore(handle, workflow_id)
        validator = MonitorSubscriptionValidator(
            resources=resources,
            workflow_id=workflow_id,
        )
        if field in {"merged", "monitor_event_subscription"}:
            selected = store.read()
            mutation = self._mutation(
                field,
                value,
                selected,
                validator,
            )
            try:
                committed = store.compare_and_update(
                    selected.workflow_revision,
                    mutation,
                )
            except SkillStateConflict as error:
                raise ProcessStateEvidenceConflict(
                    "workflow changed during external evidence read-back; rerun the command"
                ) from error
        else:
            mutation = self._mutation(
                field,
                value,
                None,
                validator,
            )
            committed = store.update(mutation)
        return self._success(field, committed)

    def _mutation(
        self,
        field: str,
        value: object,
        original: SkillStateSnapshot | None,
        validator: MonitorSubscriptionValidator,
    ) -> EvidenceMutation | VerifiedMergeMutation:
        if field == "monitor_event_subscription":
            return EvidenceMutation(
                field=field,
                value=dict(validator.validate_live(value)),
                updated_at=datetime.now(UTC).isoformat(),
            )
        if field != "merged":
            return EvidenceMutation(
                field=field,
                value=value,
                updated_at=datetime.now(UTC).isoformat(),
            )
        if original is None:
            raise ProcessStateEvidenceValidationError(
                "merged evidence requires an exact workflow snapshot"
            )
        subscription = original.skill_state.get("monitor_event_subscription")
        if subscription is None:
            raise ProcessStateEvidenceValidationError(
                "merged evidence requires a registered monitor_event_subscription read-back"
            )
        verified_subscription = validator.validate_identity(subscription)
        return VerifiedMergeMutation(
            expected_subscription=verified_subscription,
            receipt=self._merge_verifier.verify(verified_subscription),
            updated_at=datetime.now(UTC).isoformat(),
        )

    def _success(
        self,
        field: str,
        snapshot: SkillStateSnapshot,
    ) -> ProcessStateEvidenceResult:
        return ProcessStateEvidenceResult(
            exit_code=0,
            stdout=json.dumps(
                {field: snapshot.skill_state.get(field)},
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ),
            stderr="",
        )

    def _json_value(self, raw_value: str) -> object:
        try:
            return json.loads(raw_value)
        except json.JSONDecodeError as error:
            raise ProcessStateEvidenceInputError("value_json must be valid JSON") from error

    def _allowed_field(self, namespace: argparse.Namespace) -> str:
        """CLI field를 generic phase evidence allowlist로 검증합니다.

        Args:
            namespace: Parser가 구성한 command namespace입니다.

        Returns:
            공백을 제거하고 allowlist membership을 확인한 evidence field입니다.

        Raises:
            ProcessStateEvidenceValidationError: Delegate, owner, incident, ACK 등 reserved
                field를 generic helper로 변경하려 하면 발생합니다.
        """
        field = self._text(namespace, "field")
        if field not in self._ALLOWED_FIELDS:
            raise ProcessStateEvidenceValidationError(
                f"process state evidence field is reserved: {field}"
            )
        return field

    def _text(self, namespace: argparse.Namespace, name: str) -> str:
        value = getattr(namespace, name, None)
        if not isinstance(value, str) or not value.strip():
            raise ProcessStateEvidenceInputError(f"{name} must be a non-empty string")
        return value.strip()

    def _parser(self) -> ProcessStateEvidenceArgumentParser:
        parser = ProcessStateEvidenceArgumentParser(
            description="Update process-ticket workflow evidence.",
        )
        parser.add_argument("--workflow-id", required=True)
        parser.add_argument("--field", required=True)
        parser.add_argument("--value-json", required=True)
        return parser


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    result = ProcessStateEvidenceApplication().run(
        tuple(sys.argv[1:]),
        os.environ,
        Path.cwd(),
    )
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    raise SystemExit(result.exit_code)

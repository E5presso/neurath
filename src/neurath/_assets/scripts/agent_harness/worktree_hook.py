"""PreToolUse payload를 shared worktree claim authorization으로 판정합니다."""

import json
import os
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from enum import StrEnum
from pathlib import Path

from scripts.agent_harness.evaluation_loop import EVALUATE_HARNESS_MAX_WALL_CLOCK_SECONDS
from scripts.agent_harness.harness_maintenance import HarnessMaintenanceAuthority
from scripts.agent_harness.material_action import canonical_material_target
from scripts.agent_harness.material_action_runtime_hook import (
    MaterialActionRuntimeHookApplication,
)
from scripts.agent_harness.runtime_hook import RuntimeHookApplication
from scripts.agent_harness.runtime_hook_command import (
    DEFAULT_ADDITIONAL_CONTEXT_MAX_BYTES,
    DEFAULT_ENCLAVE_MAX_BYTES,
)
from scripts.agent_harness.session_kernel import (
    ActorId,
    ProcessState,
    SessionLocator,
    SessionNotFound,
    SessionRuntime,
    WorkflowStatus,
)
from scripts.agent_harness.skill_state_contract import SessionKernelError
from scripts.agent_harness.state_handle import (
    RuntimeEnvironmentResolver,
    RuntimeIdentityConflict,
    RuntimeIdentityUnavailable,
    StateHandle,
    StateHandleAuthorityError,
)
from scripts.agent_harness.tool_action_parser import (
    ToolActionEffect,
    ToolActionParser,
    ToolActionPayloadError,
)
from scripts.agent_harness.worktree_registry import (
    CanonicalWorktreeIdentity,
    WorktreeAccess,
    WorktreeIdentityAmbiguous,
    WorktreeIdentityResolver,
    WorktreeIdentityUnavailable,
    WorktreeNotClaimed,
    WorktreeOperation,
    WorktreeRegistry,
)


class WorktreeHookDecisionCode(StrEnum):
    """Hook caller와 test가 분기할 stable decision code입니다."""

    HARNESS_MAINTENANCE = "harness-maintenance"
    """Active repair lease가 exact actor와 exact harness target을 승인했습니다."""

    HOST_MANAGED = "host-managed"
    """Repository structured-edit harness 밖의 tool은 host authority에 맡깁니다."""

    OWNER = "owner"
    """Exact runtime session actor가 claimed worktree owner입니다."""

    UNCLAIMED = "unclaimed"
    """Target worktree가 claim되지 않아 explicit typed claim이 필요합니다."""

    NON_OWNER = "non-owner"
    """Claimed resource owner와 current runtime actor가 다릅니다."""

    IDENTITY_UNAVAILABLE = "identity-unavailable"
    """Claimed mutation을 authorize할 exact runtime identity가 없습니다."""

    SESSION_UNINITIALIZED = "session-uninitialized"
    """Runtime identity는 유효하지만 exact SessionStart state가 없습니다."""

    CANONICAL_STATE = "canonical-state"
    """StateHandle 밖에서 canonical state를 직접 변경하려 했습니다."""

    INVALID_INPUT = "invalid-input"
    """Hook JSON 또는 tool shape가 결정적으로 해석되지 않습니다."""

    RESOURCE_UNAVAILABLE = "resource-unavailable"
    """Target resource의 Git identity를 안전하게 증명하지 못했습니다."""

    EVALUATION_LOOP_TERMINAL = "evaluation-loop-terminal"
    """통과 또는 terminal candidate가 된 평가 run 뒤의 추가 mutation입니다."""

    EVALUATION_BUDGET_EXHAUSTED = "evaluation-budget-exhausted"
    """Bounded 평가 시간이 끝난 뒤 terminal control 외 mutation입니다."""


class WorktreeHookDisposition(StrEnum):
    """Repository worktree fence가 가진 authority의 적용 결과를 구분합니다."""

    REPOSITORY_ALLOW = "repository-allow"
    """Repository가 exact structured mutation을 직접 승인했습니다."""

    REPOSITORY_DENY = "repository-deny"
    """Repository가 exact structured mutation을 직접 거부했습니다."""

    DEFER_TO_HOST = "defer-to-host"
    """Repository 관할 밖의 tool이므로 승인 판단을 host에 남깁니다."""


class WorktreeHookDecision:
    """Repository authority disposition과 stable 원인을 묶는 immutable value입니다."""

    __slots__ = ("code", "disposition", "reason")

    def __init__(
        self,
        *,
        disposition: WorktreeHookDisposition,
        code: WorktreeHookDecisionCode,
        reason: str,
    ) -> None:
        """판정 결과를 생성 뒤 변경할 수 없게 고정합니다.

        Args:
            disposition: Repository가 allow, deny 또는 host defer 중 내린 판정입니다.
            code: Hook caller가 분기할 stable machine-readable 원인입니다.
            reason: Agent가 판정 원인과 다음 행동을 이해할 수 있는 설명입니다.
        """
        object.__setattr__(self, "disposition", disposition)
        object.__setattr__(self, "code", code)
        object.__setattr__(self, "reason", reason)

    disposition: WorktreeHookDisposition
    """Repository worktree fence의 authority 적용 결과입니다."""

    code: WorktreeHookDecisionCode
    """Machine-readable decision 원인입니다."""

    reason: str
    """Agent가 다음 행동을 선택할 수 있는 짧은 설명입니다."""

    def __setattr__(self, name: str, value: object) -> None:
        """생성 이후 decision mutation을 거부합니다.

        Args:
            name: 변경하려 한 decision attribute 이름입니다.
            value: Attribute에 새로 대입하려 한 값입니다.

        Raises:
            AttributeError: Immutable decision 생성 뒤에는 항상 발생합니다.
        """
        raise AttributeError(f"{type(self).__name__} is immutable")


class WorktreeHookResult:
    """Hook process 결과와 내부 decision을 함께 반환합니다."""

    __slots__ = ("decision", "exit_code", "stderr")

    def __init__(
        self,
        *,
        exit_code: int,
        stderr: str,
        decision: WorktreeHookDecision,
    ) -> None:
        """Vendor hook protocol output을 immutable result로 고정합니다.

        Args:
            exit_code: Vendor hook process가 반환할 allow 또는 deny exit code입니다.
            stderr: Deny일 때 vendor runtime에 전달할 serialized payload입니다.
            decision: Application test와 process adapter가 공유하는 typed 판정입니다.
        """
        object.__setattr__(self, "exit_code", exit_code)
        object.__setattr__(self, "stderr", stderr)
        object.__setattr__(self, "decision", decision)

    exit_code: int
    """Repository allow 또는 host defer이면 0, deny 또는 invalid input이면 2입니다."""

    stderr: str
    """Deny일 때 vendor가 읽을 hook-specific JSON입니다."""

    decision: WorktreeHookDecision
    """Application test와 adapter가 사용하는 typed 판정입니다."""

    def __setattr__(self, name: str, value: object) -> None:
        """생성 이후 result mutation을 거부합니다.

        Args:
            name: 변경하려 한 result attribute 이름입니다.
            value: Attribute에 새로 대입하려 한 값입니다.

        Raises:
            AttributeError: Immutable result 생성 뒤에는 항상 발생합니다.
        """
        raise AttributeError(f"{type(self).__name__} is immutable")


class HookRequest:
    """Raw vendor payload에서 정규화한 최소 PreToolUse request입니다."""

    __slots__ = (
        "effect",
        "name",
        "runtime_agent_id",
        "runtime_session_id",
        "targets",
        "workdir",
    )

    def __init__(
        self,
        *,
        name: str,
        workdir: Path,
        targets: Sequence[Path],
        effect: ToolActionEffect,
        runtime_agent_id: str | None = None,
        runtime_session_id: str | None = None,
    ) -> None:
        """Tool identity, execution resource와 literal target을 고정합니다.

        Args:
            name: Vendor payload에서 정규화한 tool identity입니다.
            workdir: Tool command가 실행될 canonical current directory입니다.
            targets: Direct mutation tool에서 해석한 literal target path 목록입니다.
            effect: Shared parser가 판정한 host 또는 structured mutation effect입니다.
            runtime_agent_id: Vendor hook payload의 optional subagent identity입니다.
            runtime_session_id: Vendor hook payload의 optional root session identity입니다.
        """
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "workdir", workdir)
        object.__setattr__(self, "targets", tuple(targets))
        object.__setattr__(self, "effect", effect)
        object.__setattr__(self, "runtime_agent_id", runtime_agent_id)
        object.__setattr__(self, "runtime_session_id", runtime_session_id)

    name: str
    """Runtime namespace와 대소문자 차이를 제거한 canonical tool 이름입니다."""

    workdir: Path
    """Structured target의 relative path를 해석하는 canonical execution directory입니다."""

    targets: tuple[Path, ...]
    """Worktree claim과 비교할 normalized absolute mutation target입니다."""

    effect: ToolActionEffect
    """Shared parser가 판정한 host-managed 또는 material-mutation effect입니다."""

    runtime_agent_id: str | None
    """Claude hook이 current child invocation에 결속한 optional actor identity입니다."""

    runtime_session_id: str | None
    """Vendor hook이 current invocation에 결속한 optional session identity입니다."""

    def __setattr__(self, name: str, value: object) -> None:
        """생성 이후 normalized request mutation을 거부합니다.

        Args:
            name: 변경하려 한 normalized request attribute 이름입니다.
            value: Attribute에 새로 대입하려 한 값입니다.

        Raises:
            AttributeError: Immutable request 생성 뒤에는 항상 발생합니다.
        """
        raise AttributeError(f"{type(self).__name__} is immutable")


class HookInputError(ValueError):
    """Raw hook payload를 deterministic request로 만들 수 없음을 나타냅니다."""


class WorktreeHookApplication:
    """Tool effect를 target worktree claim과 exact runtime actor로 대조합니다."""

    _DIRECT_MUTATION_TOOLS = frozenset({
        "apply_patch",
        "edit",
        "multiedit",
        "notebookedit",
        "write",
    })
    _CANONICAL_STATE_NAMES = frozenset({
        ".process-state.json",
        ".process-state.json.lock",
        "enclave.json",
        "enclave.json.lock",
    })

    def __init__(self, hook_runtime: SessionRuntime | None = None) -> None:
        """Stateless parser와 optional runtime-specific hook authority를 준비합니다.

        Args:
            hook_runtime: Vendor wrapper가 명시한 exact hook runtime입니다.
        """
        self._tool_actions = ToolActionParser()
        self._runtime_identities = RuntimeEnvironmentResolver()
        self._worktree_identities = WorktreeIdentityResolver()
        self._hook_runtime = hook_runtime

    def run(
        self,
        raw_input: str,
        environment: Mapping[str, object],
        cwd: Path,
    ) -> WorktreeHookResult:
        """한 PreToolUse payload를 allow 또는 deny로 완전히 판정합니다.

        Read-only request는 state를 열지 않습니다. Mutation은 literal target 또는 command
        workdir의 Git worktree identity 하나를 계산하고 그 exact shared claim만 조회합니다.
        다른 session directory나 worktree state file을 scan하지 않습니다.

        Args:
            raw_input: Vendor runtime이 stdin으로 전달한 JSON object 문자열입니다.
            environment: Exact runtime session과 actor identity를 제공하는 environment입니다.
            cwd: Hook invocation이 시작된 repository current directory입니다.

        Returns:
            Repository allow, host defer 또는 deny의 protocol output과 typed decision입니다.
        """
        try:
            request = self._parse(raw_input, cwd)
        except (HookInputError, OSError, subprocess.CalledProcessError) as error:
            return self._deny(WorktreeHookDecisionCode.INVALID_INPUT, str(error))

        if request.effect is ToolActionEffect.HOST_MANAGED:
            return self._defer_to_host(
                WorktreeHookDecisionCode.HOST_MANAGED,
                "non-edit tool authority belongs to the host runtime",
            )
        try:
            locator = SessionLocator.from_worktree(cwd)
        except (OSError, subprocess.CalledProcessError) as error:
            return self._deny(WorktreeHookDecisionCode.INVALID_INPUT, str(error))
        if HarnessMaintenanceAuthority.authorizes(
            cwd=cwd,
            environment=environment,
            hook_runtime=self._hook_runtime,
            runtime_agent_id=request.runtime_agent_id,
            runtime_session_id=request.runtime_session_id,
            tool_name=request.name,
            targets=request.targets,
        ):
            return self._allow(
                WorktreeHookDecisionCode.HARNESS_MAINTENANCE,
                "active exact-target harness maintenance lease bypasses the worktree fence",
            )
        if not request.targets:
            return self._deny(
                WorktreeHookDecisionCode.RESOURCE_UNAVAILABLE,
                "structured mutation tool requires at least one literal target",
            )
        resources = request.targets
        identities: list[CanonicalWorktreeIdentity] = []
        unresolved_targets: list[Path] = []
        for target in resources:
            canonical_target = self._canonical_target(target)
            if self._is_canonical_state(locator, canonical_target):
                return self._deny(
                    WorktreeHookDecisionCode.CANONICAL_STATE,
                    "canonical session/resource state may only be changed through StateHandle",
                )
            identity = self._resolve_target_identity(canonical_target)
            if identity is None:
                if canonical_target != request.workdir:
                    unresolved_targets.append(canonical_target)
                continue
            if identity.repository_control_root != locator.control_root:
                return self._deny(
                    WorktreeHookDecisionCode.RESOURCE_UNAVAILABLE,
                    "mutation target belongs to another repository control root",
                )
            identities.append(identity)

        try:
            binding = self._runtime_identities.resolve_hook_actor(
                environment,
                request.runtime_agent_id,
                request.runtime_session_id,
                hook_runtime=self._hook_runtime,
            )
            handle = StateHandle.attach(locator, binding)
        except (
            RuntimeIdentityUnavailable,
            RuntimeIdentityConflict,
            SessionNotFound,
            StateHandleAuthorityError,
        ):
            return self._deny(
                WorktreeHookDecisionCode.IDENTITY_UNAVAILABLE,
                "repository mutation requires exact runtime session and actor identity",
            )

        bounded_decision = self._bounded_evaluation_mutation_decision(
            handle.inspect(),
            handle.actor_id,
            request,
        )
        if bounded_decision is not None:
            return bounded_decision

        unique_identities = self._unique_identities(identities)
        if not unique_identities:
            return self._deny(
                WorktreeHookDecisionCode.RESOURCE_UNAVAILABLE,
                "mutation target is not a proven Git worktree in this repository",
            )
        if unresolved_targets:
            return self._deny(
                WorktreeHookDecisionCode.RESOURCE_UNAVAILABLE,
                "worktree mutation contains a target outside any proven Git worktree",
            )

        registry = WorktreeRegistry(locator)
        claimed: list[CanonicalWorktreeIdentity] = []
        unclaimed: list[CanonicalWorktreeIdentity] = []
        for identity in unique_identities:
            try:
                registry.get(identity.worktree_id)
            except WorktreeNotClaimed:
                unclaimed.append(identity)
            else:
                claimed.append(identity)
        for identity in claimed:
            decision = registry.authorize(
                WorktreeAccess(
                    worktree_id=identity.worktree_id,
                    session_id=handle.session_id,
                    actor_id=handle.actor_id,
                    operation=WorktreeOperation.MUTATE,
                )
            )
            if not decision.allowed:
                return self._deny(
                    WorktreeHookDecisionCode.NON_OWNER,
                    "current runtime actor does not own the target worktree claim",
                )
        if unclaimed:
            return self._deny(
                WorktreeHookDecisionCode.RESOURCE_UNAVAILABLE,
                "repository mutation requires an explicit typed worktree claim",
            )
        return self._allow(
            WorktreeHookDecisionCode.OWNER,
            "current runtime actor owns every claimed mutation target",
        )

    def _bounded_evaluation_mutation_decision(
        self,
        state: ProcessState,
        actor_id: ActorId,
        request: HookRequest,
    ) -> WorktreeHookResult | None:
        """Current actor의 evaluate-harness terminal/budget 경계를 mutation에 적용합니다.

        Args:
            state: Exact-session canonical process snapshot입니다.
            actor_id: Hook runtime이 증명한 current actor입니다.
            request: 실행 직전의 normalized tool invocation입니다.

        Returns:
            Mutation을 차단할 result 또는 일반 ownership 판정을 계속할 ``None``입니다.
        """
        workflows = tuple(
            workflow
            for workflow in state.workflows.values()
            if workflow.owner_actor_id == actor_id
            and workflow.kind == "evaluate-harness"
            and workflow.status is WorkflowStatus.ACTIVE
        )
        for workflow in workflows:
            phase_run = workflow.payload.get("phase_run")
            if not isinstance(phase_run, Mapping):
                return self._deny(
                    WorktreeHookDecisionCode.EVALUATION_BUDGET_EXHAUSTED,
                    "evaluate-harness has no bounded phase projection; return blocked control",
                )
            terminal_candidate = phase_run.get("current_phase_id") is None
            if terminal_candidate:
                return self._deny(
                    WorktreeHookDecisionCode.EVALUATION_LOOP_TERMINAL,
                    "frozen matrix verification produced a terminal candidate; finalize or wait "
                    "for an explicit new user instruction instead of mutating the repository",
                )
            started_at = phase_run.get("started_at_epoch")
            expired = (
                isinstance(started_at, (int, float))
                and not isinstance(started_at, bool)
                and max(0.0, time.time() - float(started_at))
                > EVALUATE_HARNESS_MAX_WALL_CLOCK_SECONDS
            )
            if expired:
                return self._deny(
                    WorktreeHookDecisionCode.EVALUATION_BUDGET_EXHAUSTED,
                    "evaluate-harness exceeded its 90 minute wall-clock watchdog; only blocked "
                    "or failed control return is allowed",
                )
        return None

    def _parse(self, raw_input: str, cwd: Path) -> HookRequest:
        try:
            action = self._tool_actions.parse_request(raw_input, cwd)
        except ToolActionPayloadError as error:
            raise HookInputError(str(error)) from error
        return HookRequest(
            name=action.name,
            workdir=action.workdir,
            targets=tuple(Path(target) for target in action.targets),
            effect=action.effect,
            runtime_agent_id=action.runtime_agent_id,
            runtime_session_id=action.runtime_session_id,
        )

    def _is_canonical_state(self, locator: SessionLocator, target: Path) -> bool:
        runtime_database = (locator.control_root / ".neurath/local/runtime.sqlite3").resolve()
        if target in {Path(str(runtime_database) + suffix) for suffix in ("", "-wal", "-shm", "-journal")}:
            return True
        runs_root = (__import__("scripts._neurath_paths", fromlist=["state_path"]).state_path(locator.control_root, "runs")).resolve()
        resources_root = (__import__("scripts._neurath_paths", fromlist=["state_path"]).state_path(locator.control_root, "resources")).resolve()
        return (
            target.is_relative_to(runs_root)
            and target.name in self._CANONICAL_STATE_NAMES
            or target.is_relative_to(resources_root)
            and target.suffix in {".json", ".lock"}
        )

    def _resolve_target_identity(self, target: Path) -> CanonicalWorktreeIdentity | None:
        probe = target if target.is_dir() else target.parent
        while not probe.exists() and probe != probe.parent:
            probe = probe.parent
        if not probe.is_dir():
            return None
        try:
            return self._worktree_identities.resolve(probe)
        except WorktreeIdentityUnavailable:
            return None
        except WorktreeIdentityAmbiguous:
            raise

    def _unique_identities(
        self,
        identities: Sequence[CanonicalWorktreeIdentity],
    ) -> tuple[CanonicalWorktreeIdentity, ...]:
        unique: dict[str, CanonicalWorktreeIdentity] = {}
        for identity in identities:
            unique[str(identity.worktree_id)] = identity
        return tuple(unique.values())

    def _canonical_target(self, target: Path) -> Path:
        return canonical_material_target(target)

    def _allow(
        self,
        code: WorktreeHookDecisionCode,
        reason: str,
    ) -> WorktreeHookResult:
        decision = WorktreeHookDecision(
            disposition=WorktreeHookDisposition.REPOSITORY_ALLOW,
            code=code,
            reason=reason,
        )
        return WorktreeHookResult(exit_code=0, stderr="", decision=decision)

    def _defer_to_host(
        self,
        code: WorktreeHookDecisionCode,
        reason: str,
    ) -> WorktreeHookResult:
        decision = WorktreeHookDecision(
            disposition=WorktreeHookDisposition.DEFER_TO_HOST,
            code=code,
            reason=reason,
        )
        return WorktreeHookResult(exit_code=0, stderr="", decision=decision)

    def _deny(
        self,
        code: WorktreeHookDecisionCode,
        reason: str,
    ) -> WorktreeHookResult:
        decision = WorktreeHookDecision(
            disposition=WorktreeHookDisposition.REPOSITORY_DENY,
            code=code,
            reason=reason,
        )
        payload = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": f"Neurath worktree fence [{code.value}]: {reason}",
            }
        }
        stderr = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
        return WorktreeHookResult(exit_code=2, stderr=stderr, decision=decision)


class WorktreeHookCommand:
    """Process stdin, environment와 cwd를 worktree hook application에 전달합니다."""

    def run(self, arguments: Sequence[str]) -> int:
        """Positional argument가 없을 때만 canonical hook 판정을 실행합니다.

        Args:
            arguments: Worktree hook entrypoint에 전달된 positional argument입니다.

        Returns:
            Argument가 있으면 2, 아니면 application의 allow 또는 deny exit code입니다.
        """
        parsed = tuple(arguments)
        if parsed in {(), ("composite-pre",)}:
            hook_runtime = None
        elif len(parsed) == 2 and parsed[0] == "composite-pre":
            try:
                hook_runtime = SessionRuntime(parsed[1])
            except ValueError:
                return 2
        else:
            return 2
        exit_code, stdout, stderr = self.run_payload(
            sys.stdin.read(),
            os.environ,
            Path.cwd(),
            hook_runtime=hook_runtime,
        )
        if stdout:
            sys.stdout.write(stdout)
        if stderr:
            sys.stderr.write(stderr)
        return exit_code

    def run_payload(
        self,
        raw_input: str,
        environment: Mapping[str, object],
        cwd: Path,
        *,
        hook_runtime: SessionRuntime | None = None,
    ) -> tuple[int, str, str]:
        """Worktree fence 뒤 material gate를 실행하고 optional child input을 반환합니다.

        Args:
            raw_input: Vendor PreToolUse JSON 원문입니다.
            environment: Runtime-owned vendor session environment입니다.
            cwd: Exact Git repository worktree입니다.
            hook_runtime: Wrapper가 증명한 vendor runtime이며 generic caller는 생략합니다.

        Returns:
            Process exit code, optional hook JSON stdout, diagnostic stderr입니다.
        """
        try:
            startup_context = self._recover_missing_root_session(
                raw_input,
                environment,
                cwd,
                hook_runtime,
            )
        except (
            json.JSONDecodeError,
            RuntimeIdentityConflict,
            SessionKernelError,
            StateHandleAuthorityError,
            TypeError,
            ValueError,
        ) as error:
            denied = WorktreeHookApplication(hook_runtime)._deny(
                WorktreeHookDecisionCode.SESSION_UNINITIALIZED,
                str(error),
            )
            return denied.exit_code, "", denied.stderr

        worktree = WorktreeHookApplication(hook_runtime).run(raw_input, environment, cwd)
        if worktree.exit_code != 0:
            return worktree.exit_code, "", worktree.stderr
        material = MaterialActionRuntimeHookApplication(hook_runtime).run(
            "pre",
            raw_input,
            environment,
            cwd,
        )
        if material.exit_code != 0:
            return material.exit_code, "", material.stderr
        if startup_context is None:
            return 0, "", ""
        specific: dict[str, object] = {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
        }
        if startup_context is not None:
            specific["additionalContext"] = startup_context
        payload = {"hookSpecificOutput": specific}
        return 0, json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", ""

    def _recover_missing_root_session(
        self,
        raw_input: str,
        environment: Mapping[str, object],
        cwd: Path,
        hook_runtime: SessionRuntime | None,
    ) -> str | None:
        """Skipped SessionStart로 완전히 빈 root state만 startup lifecycle로 복구합니다.

        Existing, foreign child, identity-conflicted, partial/corrupt state는 변경하지
        않습니다. Codex가 각 hook에 동일하게 제공하는 session_id를 vendor
        environment와 exact 대조한 뒤 기존 RuntimeHook startup을 그대로 재사용합니다.
        """
        decoded = json.loads(raw_input)
        if not isinstance(decoded, dict):
            raise TypeError("PreToolUse payload must be a JSON object")
        runtime_session_id = decoded.get("session_id")
        resolver = RuntimeEnvironmentResolver()
        try:
            binding = resolver.resolve_hook_actor(
                environment,
                None,
                runtime_session_id,
                hook_runtime=hook_runtime,
            )
        except RuntimeIdentityConflict, RuntimeIdentityUnavailable:
            return None
        if not binding.is_root:
            return None

        locator = SessionLocator.from_worktree(cwd)
        try:
            StateHandle.attach(locator, binding).inspect()
            return None
        except SessionNotFound:
            pass

        if decoded.get("hook_event_name") != "PreToolUse":
            raise ValueError("missing session recovery requires PreToolUse provenance")
        if decoded.get("session_id") != str(binding.session_id):
            raise RuntimeIdentityConflict(
                "PreToolUse session_id conflicts with the runtime-owned root identity"
            )

        startup_payload = {
            key: decoded[key]
            for key in (
                "session_id",
                "transcript_path",
                "cwd",
                "model",
                "permission_mode",
            )
            if key in decoded
        }
        startup_payload["hook_event_name"] = "SessionStart"
        startup_payload["source"] = "startup"
        startup_environment = {key: str(value) for key, value in environment.items()}
        startup_environment["NEURATH_HOOK_RUNTIME"] = binding.runtime.value
        application = RuntimeHookApplication(
            locator,
            enclave_max_bytes=DEFAULT_ENCLAVE_MAX_BYTES,
            additional_context_max_bytes=DEFAULT_ADDITIONAL_CONTEXT_MAX_BYTES,
        )
        result = application.run(
            json.dumps(startup_payload, ensure_ascii=False, separators=(",", ":")),
            startup_environment,
        )
        if result.exit_code != 0:
            raise SessionKernelError(
                f"SessionStart recovery failed: {result.diagnostic or 'unknown diagnostic'}"
            )
        output = json.loads(result.stdout)
        specific = output.get("hookSpecificOutput")
        context = specific.get("additionalContext") if isinstance(specific, dict) else None
        if context is not None and not isinstance(context, str):
            raise ValueError("SessionStart recovery context must be a string")
        application.acknowledge(result)
        return context


if __name__ == "__main__":
    raise SystemExit(WorktreeHookCommand().run(sys.argv[1:]))

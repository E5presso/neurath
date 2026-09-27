"""PR monitor runtime 하나를 exact session workflow에 안전하게 인계합니다."""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import shlex
import shutil
import signal
import subprocess
import sys
import time
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
SCRIPT_DIRECTORY = Path(__file__).resolve().parent
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

from monitor_observation_store import MonitorObservationStore
from monitor_runtime_lock import MonitorRuntimeCommitLock

from scripts.agent_harness.session_kernel import (
    SessionKernelError,
    SessionLocator,
    WorkflowId,
)
from scripts.agent_harness.skill_state_store import SkillStateSnapshot, SkillStateStore
from scripts.agent_harness.state_handle import (
    RuntimeEnvironmentResolver,
    RuntimeIdentityError,
    StateHandle,
)
from scripts.agent_harness.worktree_registry import (
    WorktreeIdentityResolver,
    WorktreeRegistryError,
)


from monitor_handoff_plan import (
    MonitorRuntimeHandoffError as MonitorRuntimeHandoffError,
    MonitorRuntimeIdentityMismatch as MonitorRuntimeIdentityMismatch,
    MonitorRuntimeRetirementFailed as MonitorRuntimeRetirementFailed,
    LegacyMonitorStateInvalid as LegacyMonitorStateInvalid,
    MonitorExternalFileConflict as MonitorExternalFileConflict,
    MonitorRuntimeHandoffResult as MonitorRuntimeHandoffResult,
    MonitorRuntimePaths as MonitorRuntimePaths,
    DetachedRuntimeTarget as DetachedRuntimeTarget,
    PreparedFileTarget as PreparedFileTarget,
    PreparedFileClaim as PreparedFileClaim,
    LaunchAgentTarget as LaunchAgentTarget,
    MonitorHandoffPlan as MonitorHandoffPlan,
)
from monitor_handoff_state import (
    MonitorWorkflowSnapshotValidator as MonitorWorkflowSnapshotValidator,
    MonitorHandoffPreparedMutation as MonitorHandoffPreparedMutation,
    MonitorHandoffCompletedMutation as MonitorHandoffCompletedMutation,
)

class MonitorRuntimeInventory:
    """Local process manager와 LaunchAgent의 exact obsolete runtime만 퇴역시킵니다."""

    def __init__(
        self,
        *,
        paths: MonitorRuntimePaths,
        session_id: str,
        workflow_id: str,
    ) -> None:
        """Detached process를 식별할 route fragments를 고정합니다.

        Args:
            paths: Git identity에서 파생된 canonical local runtime paths입니다.
            session_id: Process command의 exact root session identity입니다.
            workflow_id: Process command의 exact workflow identity입니다.
        """
        self._paths = paths
        self._session_id = session_id
        self._workflow_id = workflow_id

    def detached_targets(
        self,
        state: Mapping[str, object],
    ) -> tuple[DetachedRuntimeTarget, ...]:
        """Exact subscription이 가리키는 live process를 read-only로 inventory합니다.

        Args:
            state: Runtime route receipt를 가진 validated workflow skill state입니다.

        Returns:
            Durable prepared plan에 넣을 exact PID와 command targets입니다.

        Raises:
            MonitorRuntimeIdentityMismatch: Detached receipt가 subscription 없이 존재하면
                발생합니다.
        """
        subscription = state.get("monitor_event_subscription")
        started = state.get("monitor_started")
        if subscription is None:
            if isinstance(started, Mapping) and started.get("launcher") == "nohup":
                raise MonitorRuntimeIdentityMismatch(
                    "detached monitor subscription identity is missing"
                )
            return ()
        if not isinstance(subscription, Mapping):
            raise MonitorRuntimeIdentityMismatch("monitor event subscription must be an object")
        route = started if isinstance(started, Mapping) else subscription
        if route.get("launcher") != "nohup":
            return ()
        return self._matching_detached_processes(route, subscription)

    def retire_detached(
        self,
        targets: tuple[DetachedRuntimeTarget, ...],
    ) -> tuple[int, ...]:
        """Prepared plan의 exact process가 아직 같을 때만 종료합니다.

        Missing process 또는 다른 command로 재사용된 PID는 prepared target이 이미
        사라진 것으로 판정해 성공 read-back합니다.

        Args:
            targets: Prepared CAS가 승인한 exact process identities입니다.

        Returns:
            Exact target이 모두 사라졌음을 read-back한 process ID 목록입니다.
        """
        for target in targets:
            readback = self._process_command(target.pid)
            if readback is None or readback != target.command:
                continue
            try:
                os.kill(target.pid, signal.SIGTERM)
            except ProcessLookupError:
                continue
            self._wait_for_process_exit(target)
        return tuple(target.pid for target in targets)

    def launch_agent_targets(self, expected_label: str) -> tuple[LaunchAgentTarget, ...]:
        """Expected label 외의 worktree-local plist를 read-only로 inventory합니다.

        Args:
            expected_label: 새 monitor가 이어서 사용할 유일한 LaunchAgent label입니다.
        Returns:
            Durable prepared plan에 넣을 exact label/plist targets입니다.
        """
        if not self._paths.state_dir.is_dir():
            return ()
        targets: list[LaunchAgentTarget] = []
        for plist_path in sorted(self._paths.state_dir.glob("*.plist")):
            file_target = PreparedFileTarget.capture(
                role="launch-agent-plist",
                path=plist_path,
            )
            label = self._plist_label(file_target)
            if not label or label == expected_label:
                continue
            targets.append(LaunchAgentTarget(label=label, file_target=file_target))
        return tuple(targets)

    def retire_launch_agents(
        self,
        targets: tuple[tuple[LaunchAgentTarget, PreparedFileClaim], ...],
        *,
        launchctl_path: str,
        user_id: int,
    ) -> tuple[str, ...]:
        """Prepared plist claim이 증명하는 exact LaunchAgents만 idempotently unload합니다.

        Args:
            targets: Commit lock 아래 확보한 exact LaunchAgent/plist claims입니다.
            launchctl_path: Prepared plan에 고정된 launchctl executable입니다.
            user_id: Prepared plan에 고정된 GUI domain user identity입니다.

        Returns:
            Exact claim으로 unload했거나 launchd 부재를 read-back한 labels입니다.
        """
        retired: list[str] = []
        for target, claim in targets:
            if not claim.present:
                if launchctl_path and self._launch_agent_is_absent(
                    launchctl_path,
                    target.label,
                    user_id,
                ):
                    retired.append(target.label)
                continue
            claim.verify()
            if launchctl_path:
                self._retire_launch_agent(launchctl_path, target.label, user_id)
            retired.append(target.label)
        return tuple(retired)

    def _matching_detached_processes(
        self,
        route: Mapping[str, object],
        subscription: Mapping[str, object],
    ) -> tuple[DetachedRuntimeTarget, ...]:
        runtime_id = route.get("runtime_id")
        if not isinstance(runtime_id, str) or not runtime_id:
            raise MonitorRuntimeIdentityMismatch(
                "detached monitor runtime fencing identity is missing"
            )
        repo = subscription.get("repo")
        pr_number = subscription.get("pr_number")
        if not isinstance(repo, str) or not repo:
            raise MonitorRuntimeIdentityMismatch("detached monitor repo identity is missing")
        if not isinstance(pr_number, int) or isinstance(pr_number, bool) or pr_number <= 0:
            raise MonitorRuntimeIdentityMismatch("detached monitor PR identity is missing")
        matches: list[DetachedRuntimeTarget] = []
        for field in ("pid", "manager_pid"):
            raw_pid = route.get(field)
            if raw_pid is None:
                continue
            if not isinstance(raw_pid, int) or isinstance(raw_pid, bool) or raw_pid <= 0:
                raise MonitorRuntimeIdentityMismatch(f"detached monitor {field} receipt is invalid")
            command = self._process_command(raw_pid)
            if command is None:
                continue
            if not self._matches_command(
                command,
                repo=repo,
                pr_number=pr_number,
                runtime_id=runtime_id,
            ):
                raise MonitorRuntimeIdentityMismatch(
                    f"detached monitor {field} process identity mismatch"
                )
            if all(target.pid != raw_pid for target in matches):
                matches.append(DetachedRuntimeTarget(pid=raw_pid, command=command))
        return tuple(matches)

    def _matches_command(
        self,
        command_text: str,
        *,
        repo: str,
        pr_number: int,
        runtime_id: str,
    ) -> bool:
        try:
            command = shlex.split(command_text)
        except ValueError:
            return False
        return (
            any(Path(part).name == "local_pr_monitor.py" for part in command)
            and self._option_matches(command, "--repo", repo)
            and self._option_matches(command, "--pr-number", str(pr_number))
            and self._option_matches(command, "--workflow-id", self._workflow_id)
            and self._option_matches(command, "--runtime-id", runtime_id)
            and self._option_matches(command, "--launcher", "nohup")
        )

    def _option_matches(
        self,
        command: Sequence[str],
        option: str,
        expected: str,
    ) -> bool:
        try:
            index = command.index(option)
        except ValueError:
            return False
        return index + 1 < len(command) and command[index + 1] == expected

    def _process_command(self, pid: int) -> str | None:
        readback = subprocess.run(
            ("ps", "-p", str(pid), "-o", "command="),
            capture_output=True,
            text=True,
            check=False,
        )
        return readback.stdout if readback.returncode == 0 else None

    def _wait_for_process_exit(self, target: DetachedRuntimeTarget) -> None:
        for _attempt in range(50):
            command = self._process_command(target.pid)
            if command is None or command != target.command:
                return
            time.sleep(0.1)
        raise MonitorRuntimeRetirementFailed(f"detached monitor process did not stop: {target.pid}")

    def _plist_label(self, target: PreparedFileTarget) -> str:
        try:
            content = target.read_if_current()
            if content is None:
                return ""
            payload = plistlib.loads(content)
        except plistlib.InvalidFileException:
            return ""
        if not isinstance(payload, dict):
            return ""
        label = payload.get("Label")
        return label if isinstance(label, str) and label else ""

    def _retire_launch_agent(self, launchctl: str, label: str, user_id: int) -> None:
        domain_target = f"gui/{user_id}/{label}"
        initial = subprocess.run(
            (launchctl, "print", domain_target),
            capture_output=True,
            text=True,
            check=False,
        )
        if initial.returncode != 0:
            return
        subprocess.run(
            (launchctl, "bootout", domain_target),
            capture_output=True,
            text=True,
            check=False,
        )
        subprocess.run(
            (launchctl, "remove", label),
            capture_output=True,
            text=True,
            check=False,
        )
        readback = subprocess.run(
            (launchctl, "print", domain_target),
            capture_output=True,
            text=True,
            check=False,
        )
        if readback.returncode == 0:
            raise MonitorRuntimeRetirementFailed(
                f"obsolete monitor runtime is still loaded: {label}"
            )

    def _launch_agent_is_absent(self, launchctl: str, label: str, user_id: int) -> bool:
        """Prepared plist claim이 이미 없을 때 label 부재만 read-back합니다.

        Args:
            launchctl: Prepared plan에 고정된 exact executable path입니다.
            label: Unload 권한 없이 부재만 확인할 prepared LaunchAgent label입니다.
            user_id: Prepared plan에 고정된 GUI domain user identity입니다.

        Returns:
            Exact GUI domain read-back에서 label이 missing이면 True입니다.

        Raises:
            MonitorRuntimeRetirementFailed: Claim 없는 label이 loaded 상태면 발생합니다.
        """
        domain_target = f"gui/{user_id}/{label}"
        readback = subprocess.run(
            (launchctl, "print", domain_target),
            capture_output=True,
            text=True,
            check=False,
        )
        if readback.returncode == 0:
            raise MonitorRuntimeRetirementFailed(
                f"obsolete monitor runtime is loaded without prepared plist claim: {label}"
            )
        return True


class LegacyMonitorState:
    """한 legacy local monitor snapshot과 migration 정렬 근거를 묶습니다."""

    __slots__ = ("path", "payload", "recency")

    def __init__(self, path: Path, payload: Mapping[str, object], recency: float) -> None:
        """Compatibility reader가 검증한 snapshot을 고정합니다.

        Args:
            path: One-way migration 뒤 제거할 local state path입니다.
            payload: JSON object로 검증된 legacy state입니다.
            recency: Baseline 선택에 사용할 heartbeat 또는 mtime입니다.
        """
        self.path = path
        self.payload = dict(payload)
        self.recency = recency

    path: Path
    """One-way migration input인 obsolete local state path입니다."""

    payload: Mapping[str, object]
    """Legacy monitor가 마지막으로 기록한 JSON object입니다."""

    recency: float
    """가장 최신 observation baseline을 고르는 정렬 값입니다."""


class LegacyMonitorFileStore:
    """Compatibility JSON을 current monitor와 공유하지 않는 atomic file boundary입니다."""

    def read(self, target: PreparedFileTarget) -> Mapping[str, object]:
        """Legacy file에서 JSON object만 읽습니다.

        Args:
            target: One-way migration input의 prepared regular-file fingerprint입니다.

        Returns:
            JSON root가 object임을 검증한 snapshot입니다.

        Raises:
            LegacyMonitorStateInvalid: JSON root가 object가 아닐 때 발생합니다.
            OSError: Input을 읽을 수 없을 때 발생합니다.
            json.JSONDecodeError: Input JSON이 손상됐을 때 발생합니다.
        """
        content = target.read_if_current()
        if content is None:
            raise MonitorExternalFileConflict(
                f"external file fingerprint conflict: missing inventory target: {target.path}"
            )
        payload = json.loads(content.decode("utf-8"))
        if not isinstance(payload, dict):
            raise LegacyMonitorStateInvalid(f"{target.path} must contain a JSON object")
        return payload


class LegacyMonitorMigration:
    """Worktree-local monitor state를 한 번 읽어 canonical workflow mailbox로 옮깁니다."""

    _MIGRATABLE_REASONS = frozenset({
        "comments-changed",
        "ci-failed",
        "merge-dirty",
        "review-blocked",
        "mergeable-clean",
        "merged",
        "closed-without-merge",
    })

    def __init__(self, paths: MonitorRuntimePaths) -> None:
        """Compatibility input과 current local state의 canonical 경계를 고정합니다.

        Args:
            paths: Current worktree의 local monitor runtime paths입니다.
        """
        self._paths = paths
        self._files = LegacyMonitorFileStore()
        self._observations = MonitorObservationStore(paths.state_path)

    def inventory(
        self,
        targets: tuple[PreparedFileTarget, ...],
    ) -> tuple[LegacyMonitorState, ...]:
        """Canonical current state를 제외한 obsolete `*-state.json`만 읽습니다.

        Args:
            targets: 한 번의 directory inventory에서 capture한 exact legacy files입니다.

        Returns:
            읽을 수 있는 legacy JSON object snapshot 목록입니다.
        """
        states: list[LegacyMonitorState] = []
        for target in targets:
            try:
                payload = self._files.read(target)
            except json.JSONDecodeError, LegacyMonitorStateInvalid, UnicodeDecodeError:
                continue
            states.append(
                LegacyMonitorState(
                    target.path,
                    payload,
                    self._recency(target.path, payload),
                )
            )
        return tuple(states)

    def obsolete_targets(self) -> tuple[PreparedFileTarget, ...]:
        """읽기 성공 여부와 무관하게 obsolete state fingerprints를 capture합니다.

        Returns:
            Canonical current state를 제외한 exact regular-file optimistic keys입니다.
        """
        if not self._paths.state_dir.is_dir():
            return ()
        return tuple(
            PreparedFileTarget.capture(role="legacy-state", path=candidate)
            for candidate in sorted(self._paths.state_dir.glob("*-state.json"))
            if PreparedFileTarget._lexical_path(candidate)
            != PreparedFileTarget._lexical_path(self._paths.state_path)
        )

    def events(
        self,
        states: tuple[LegacyMonitorState, ...],
    ) -> tuple[Mapping[str, object], ...]:
        """Live rescan 없이 재큐잉해도 안전한 event만 중복 없이 반환합니다.

        Args:
            states: 읽을 수 있는 legacy local monitor snapshots입니다.

        Returns:
            Stable event identity와 허용 reason을 가진 event 목록입니다.
        """
        migrated: list[Mapping[str, object]] = []
        seen: set[str] = set()
        for state in states:
            event = state.payload.get("last_event")
            if not isinstance(event, Mapping):
                continue
            event_id = self._event_id(event)
            reason = event.get("reason")
            if (
                not event_id
                or event_id in seen
                or event_id in self._acknowledged_event_ids(state.payload)
                or not isinstance(reason, str)
                or reason not in self._MIGRATABLE_REASONS
            ):
                continue
            seen.add(event_id)
            migrated.append(dict(event))
        return tuple(migrated)

    def suppressed_event_ids(
        self,
        states: tuple[LegacyMonitorState, ...],
    ) -> tuple[str, ...]:
        """Live aggregate 재검증이 필요해 mailbox에 넣지 않은 event identity를 반환합니다.

        Args:
            states: 읽을 수 있는 legacy local monitor snapshots입니다.

        Returns:
            Automatic 또는 delegate-result event처럼 rescan해야 하는 identity입니다.
        """
        suppressed: list[str] = []
        for state in states:
            event = state.payload.get("last_event")
            if not isinstance(event, Mapping):
                continue
            event_id = self._event_id(event)
            reason = event.get("reason")
            if (
                event_id
                and event_id not in self._acknowledged_event_ids(state.payload)
                and reason not in self._MIGRATABLE_REASONS
            ):
                suppressed.append(event_id)
        return tuple(dict.fromkeys(suppressed))

    def baseline_plan(
        self,
        states: tuple[LegacyMonitorState, ...],
        suppressed_event_ids: tuple[str, ...],
    ) -> tuple[str, Mapping[str, object] | None]:
        """Current state가 없을 때 쓸 baseline action을 read-only로 계산합니다.

        Args:
            states: 읽을 수 있는 legacy local monitor snapshots입니다.
            suppressed_event_ids: Mailbox 대신 live rescan으로 넘긴 event identities입니다.

        Returns:
            Baseline source path와 persisted payload이며 action이 없으면 빈 값들입니다.
        """
        if not states or self._observations.exists():
            return "", None
        source = max(states, key=lambda state: state.recency)
        baseline = self._observation_baseline(source.payload)
        payload: dict[str, object] = {
            "schema_version": 3,
            "provider": "local-pr-monitor",
            "legacy_handoff": {
                "source_state_path": str(source.path),
                "suppressed_legacy_event_ids": list(suppressed_event_ids),
            },
        }
        if baseline:
            payload["last_seen"] = dict(baseline)
            payload["last_observed"] = dict(baseline)
        return str(source.path), payload

    def write_baseline(self, payload: Mapping[str, object] | None) -> None:
        """Commit the prepared baseline only if no current observation exists."""
        if payload is not None:
            self._observations.write_if_absent(payload)

    def remove(self, claims: tuple[PreparedFileClaim, ...]) -> tuple[str, ...]:
        """Workflow prepared receipt 뒤 exact obsolete state만 제거합니다.

        Args:
            claims: Commit lock 아래 확보한 one-way migration input claims입니다.

        Returns:
            Exact claim을 unlink했거나 이미 absent로 확인한 original path 목록입니다.
        """
        removed: list[str] = []
        for claim in claims:
            claim.discard()
            removed.append(str(claim.target.path))
        return tuple(removed)

    def _event_id(self, event: Mapping[str, object]) -> str:
        event_id = event.get("event_id")
        return event_id if isinstance(event_id, str) and event_id else ""

    def _acknowledged_event_ids(self, state: Mapping[str, object]) -> frozenset[str]:
        event_ids: set[str] = set()
        last_acknowledged = state.get("last_acknowledged_event_id")
        if isinstance(last_acknowledged, str) and last_acknowledged:
            event_ids.add(last_acknowledged)
        monitor_ack = state.get("monitor_event_ack")
        if isinstance(monitor_ack, Mapping):
            event_id = self._event_id(monitor_ack)
            if event_id:
                event_ids.add(event_id)
        return frozenset(event_ids)

    def _recency(self, path: Path, state: Mapping[str, object]) -> float:
        heartbeat = state.get("heartbeat_at_epoch")
        if isinstance(heartbeat, int | float) and not isinstance(heartbeat, bool):
            return float(heartbeat)
        try:
            return path.stat().st_mtime
        except OSError:
            return 0.0

    def _observation_baseline(self, state: Mapping[str, object]) -> dict[str, object]:
        last_observed = state.get("last_observed")
        last_seen = state.get("last_seen")
        baseline = dict(last_observed) if isinstance(last_observed, Mapping) else {}
        if not baseline and isinstance(last_seen, Mapping):
            baseline = dict(last_seen)
        event = state.get("last_event")
        if not isinstance(event, Mapping):
            return baseline
        observation = event.get("observation")
        if isinstance(observation, Mapping):
            baseline["observation"] = dict(observation)
        fingerprint = event.get("fingerprint")
        if isinstance(fingerprint, Mapping):
            comments = fingerprint.get("comments")
            if isinstance(comments, Mapping):
                baseline["comments"] = dict(comments)
        snapshot = event.get("snapshot")
        if isinstance(snapshot, Mapping):
            for field in ("headRefOid", "reviewDecision"):
                value = snapshot.get(field)
                if isinstance(value, str):
                    baseline[field] = value
        return baseline


class MonitorRuntimeHandoffService:
    """Runtime retirement, compatibility migration, workflow receipt를 순서대로 수행합니다."""

    def __init__(
        self,
        *,
        handle: StateHandle,
        workflow_id: WorkflowId,
        paths: MonitorRuntimePaths,
    ) -> None:
        """Exact session actor, workflow, worktree boundary에 handoff service를 고정합니다.

        Args:
            handle: Runtime identity와 current actor에 결속된 canonical state facade입니다.
            workflow_id: Monitor owner lifecycle을 소유하는 exact workflow입니다.
            paths: Git identity가 증명한 local monitor runtime paths입니다.
        """
        self._handle = handle
        self._workflow_id = workflow_id
        self._paths = paths
        self._store = SkillStateStore(handle, workflow_id)
        self._validator = MonitorWorkflowSnapshotValidator(
            session_id=str(handle.session_id),
            workflow_id=str(workflow_id),
            paths=paths,
        )
        self._inventory = MonitorRuntimeInventory(
            paths=paths,
            session_id=str(handle.session_id),
            workflow_id=str(workflow_id),
        )
        self._migration = LegacyMonitorMigration(paths)
        self._commit_lock = MonitorRuntimeCommitLock(paths.state_dir)

    def prepare(self, *, expected_label: str, user_id: int) -> Mapping[str, object]:
        """Prepared CAS 뒤 exact external plan을 실행하고 completion을 CAS합니다.

        Args:
            expected_label: 새 monitor가 사용할 유일한 LaunchAgent label입니다.
            user_id: LaunchAgent GUI domain의 current macOS user identity입니다.

        Returns:
            Process retirement, legacy migration, live rescan 요구를 담은 receipt입니다.

        Raises:
            MonitorRuntimeHandoffError: Identity, lifecycle, retirement read-back이 실패하면
                side effect 이후 단계로 진행하지 않습니다.
            SessionKernelError: Workflow-local optimistic state commit이 실패할 때 발생합니다.
        """
        original = self._store.read()
        self._validator.validate(original.skill_state)
        existing = original.skill_state.get("monitor_runtime_handoff")
        if isinstance(existing, Mapping) and existing.get("state") in {"prepared", "completed"}:
            plan = MonitorHandoffPlan.from_receipt(
                existing,
                paths=self._paths,
                session_id=str(self._handle.session_id),
                workflow_id=str(self._workflow_id),
                expected_label=expected_label,
                user_id=user_id,
            )
            if existing.get("state") == "completed":
                return dict(existing)
            return self._execute_prepared(original, plan)
        if existing is not None and not isinstance(existing, Mapping):
            raise MonitorRuntimeIdentityMismatch("monitor handoff receipt must be an object")

        plan, migrated_events = self._candidate_plan(
            original,
            expected_label=expected_label,
            user_id=user_id,
        )
        prepared_at = datetime.now(UTC).isoformat()
        mailbox_updated_at_epoch = time.time()
        prepared = self._store.compare_and_update(
            original.workflow_revision,
            MonitorHandoffPreparedMutation(
                session_id=str(self._handle.session_id),
                workflow_id=str(self._workflow_id),
                worktree=str(self._paths.worktree.resolve()),
                prepared_at=prepared_at,
                mailbox_updated_at_epoch=mailbox_updated_at_epoch,
                receipt=plan.to_receipt(self._paths),
                migrated_events=migrated_events,
            ),
        )
        persisted = prepared.skill_state.get("monitor_runtime_handoff")
        persisted_plan = MonitorHandoffPlan.from_receipt(
            persisted,
            paths=self._paths,
            session_id=str(self._handle.session_id),
            workflow_id=str(self._workflow_id),
            expected_label=expected_label,
            user_id=user_id,
        )
        return self._execute_prepared(prepared, persisted_plan)

    def _candidate_plan(
        self,
        original: SkillStateSnapshot,
        *,
        expected_label: str,
        user_id: int,
    ) -> tuple[MonitorHandoffPlan, tuple[Mapping[str, object], ...]]:
        """Exact snapshot에서 side-effect-free external plan과 mailbox input을 계산합니다."""
        detached_targets = self._inventory.detached_targets(original.skill_state)
        launch_agent_targets = self._inventory.launch_agent_targets(expected_label)
        obsolete_targets = self._migration.obsolete_targets()
        legacy_states = self._migration.inventory(obsolete_targets)
        migrated_events = self._migration.events(legacy_states)
        suppressed_event_ids = self._migration.suppressed_event_ids(legacy_states)
        baseline_source, baseline_payload = self._migration.baseline_plan(
            legacy_states,
            suppressed_event_ids,
        )
        return (
            MonitorHandoffPlan(
                handoff_id=uuid.uuid4().hex,
                expected_label=expected_label,
                user_id=user_id,
                launchctl_path=shutil.which("launchctl") or "",
                detached_targets=detached_targets,
                launch_agent_targets=launch_agent_targets,
                state_targets=obsolete_targets,
                baseline_source_path=baseline_source,
                baseline_payload=baseline_payload,
                suppressed_event_ids=suppressed_event_ids,
            ),
            migrated_events,
        )

    def _execute_prepared(
        self,
        prepared: SkillStateSnapshot,
        plan: MonitorHandoffPlan,
    ) -> Mapping[str, object]:
        """Persisted external plan을 idempotently 실행하고 exact prepared revision을 완료합니다."""
        plan.verify_file_targets()
        with self._commit_lock:
            plan.verify_file_targets()
            launch_claims, state_claims = plan.claim_file_targets()
        try:
            retired_detached_pids = self._inventory.retire_detached(plan.detached_targets)
            retired_labels = self._inventory.retire_launch_agents(
                launch_claims,
                launchctl_path=plan.launchctl_path,
                user_id=plan.user_id,
            )
        except MonitorRuntimeHandoffError:
            with self._commit_lock:
                for _target, claim in reversed(launch_claims):
                    claim.restore()
                for claim in reversed(state_claims):
                    claim.restore()
            raise
        with self._commit_lock:
            plan.verify_file_targets()
            self._migration.write_baseline(plan.baseline_payload)
            for _target, claim in launch_claims:
                claim.discard()
            removed = self._migration.remove(state_claims)
        completed_at = datetime.now(UTC).isoformat()
        committed = self._store.compare_and_update(
            prepared.workflow_revision,
            MonitorHandoffCompletedMutation(
                handoff_id=plan.handoff_id,
                completed_at=completed_at,
                retired_detached_pids=retired_detached_pids,
                retired_labels=retired_labels,
                removed_state_paths=removed,
            ),
        )
        receipt = committed.skill_state.get("monitor_runtime_handoff")
        if not isinstance(receipt, Mapping):
            raise MonitorRuntimeIdentityMismatch("completed monitor handoff is missing")
        return dict(receipt)


class MonitorRuntimeHandoffApplication:
    """CLI input을 runtime-owned identity와 exact workflow handoff로 연결합니다."""

    def __init__(self) -> None:
        """Runtime identity와 Git worktree resolver를 application에 귀속시킵니다."""
        self._runtime_resolver = RuntimeEnvironmentResolver()
        self._worktree_resolver = WorktreeIdentityResolver()

    def run(
        self,
        arguments: Sequence[str],
        environment: Mapping[str, object],
        cwd: Path,
    ) -> MonitorRuntimeHandoffResult:
        """Manual state path 없이 current session workflow handoff를 실행합니다.

        Args:
            arguments: Required workflow ID, expected label, user ID만 담은 CLI arguments입니다.
            environment: Vendor runtime이 소유한 exact session/actor identity입니다.
            cwd: SessionLocator와 Git worktree identity를 해석할 current directory입니다.

        Returns:
            성공 receipt 또는 fail-closed diagnostic을 담은 process result입니다.

        Raises:
            SystemExit: Argparse가 지원하지 않는 option 또는 누락된 필수 option을 만나면
                발생합니다.
        """
        try:
            namespace = self._parser().parse_args(tuple(arguments))
            locator = SessionLocator.from_worktree(cwd)
            worktree = self._worktree_resolver.resolve(cwd)
            if locator.control_root.resolve() != worktree.repository_control_root.resolve():
                raise MonitorRuntimeIdentityMismatch(
                    "session locator and worktree control root mismatch"
                )
            binding = self._runtime_resolver.resolve(environment)
            handle = StateHandle.attach(locator, binding)
            workflow_id = WorkflowId(self._text(namespace, "workflow_id"))
            expected_label = self._text(namespace, "expected_label")
            user_id = self._user_id(namespace)
            receipt = MonitorRuntimeHandoffService(
                handle=handle,
                workflow_id=workflow_id,
                paths=MonitorRuntimePaths(worktree),
            ).prepare(expected_label=expected_label, user_id=user_id)
            return MonitorRuntimeHandoffResult(
                exit_code=0,
                stdout=json.dumps(
                    dict(receipt),
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                stderr="",
            )
        except (
            json.JSONDecodeError,
            MonitorRuntimeHandoffError,
            OSError,
            RuntimeIdentityError,
            SessionKernelError,
            subprocess.CalledProcessError,
            WorktreeRegistryError,
        ) as error:
            return MonitorRuntimeHandoffResult(
                exit_code=2,
                stdout="",
                stderr=str(error),
            )

    def _parser(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(
            description="Prepare one exact session workflow local PR monitor runtime."
        )
        parser.add_argument("--workflow-id", required=True)
        parser.add_argument("--expected-label", required=True)
        parser.add_argument("--user-id", required=True, type=int)
        return parser

    def _text(self, namespace: argparse.Namespace, name: str) -> str:
        value = getattr(namespace, name, None)
        if not isinstance(value, str) or not value.strip():
            raise MonitorRuntimeIdentityMismatch(f"{name} must be a non-empty string")
        return value.strip()

    def _user_id(self, namespace: argparse.Namespace) -> int:
        value = getattr(namespace, "user_id", None)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise MonitorRuntimeIdentityMismatch("user_id must be a non-negative integer")
        return value


class MonitorRuntimeHandoffEntrypoint:
    """Current process defaults를 path-free handoff application에 전달합니다."""

    def run(self) -> int:
        """Runtime environment와 current cwd에서 CLI를 실행합니다.

        Returns:
            Application이 결정한 process exit code입니다.
        """
        result = MonitorRuntimeHandoffApplication().run(
            tuple(sys.argv[1:]),
            os.environ,
            Path.cwd(),
        )
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        return result.exit_code


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    raise SystemExit(MonitorRuntimeHandoffEntrypoint().run())

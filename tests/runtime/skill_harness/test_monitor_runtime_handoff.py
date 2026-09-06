"""PR monitor runtime handoff의 session-scoped 상태 계약을 검증합니다."""

import importlib.util
import json
import plistlib
import signal
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast
from unittest import TestCase
from unittest.mock import patch

from scripts.agent_harness.session_kernel import (
    SessionLocator,
    WorkflowId,
    WorkflowStarted,
)
from scripts.agent_harness.skill_state_store import (
    SkillStateConflict,
    SkillStateStore,
)
from scripts.agent_harness.state_handle import (
    RuntimeEnvironmentResolver,
    StateHandle,
)

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / ".agents/skills/monitor-pr/scripts/monitor_runtime_handoff.py"
SPEC = importlib.util.spec_from_file_location("monitor_runtime_handoff", SCRIPT)
assert SPEC is not None
monitor_runtime_handoff = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(monitor_runtime_handoff)


class HandoffResultView:
    """Dynamically loaded script result의 test-facing structural view입니다."""

    exit_code: int
    """Application process exit code입니다."""

    stdout: str
    """성공 receipt JSON입니다."""

    stderr: str
    """Fail-closed diagnostic입니다."""


class SubprocessCommandRouter:
    """Git identity commands는 실행하고 monitor process commands만 fixture로 대체합니다."""

    def __init__(
        self,
        root: Path,
        results: tuple[subprocess.CompletedProcess[str], ...] = (),
    ) -> None:
        """Non-Git command에 순서대로 반환할 process 결과를 고정합니다.

        Args:
            results: Monitor process inventory와 launchctl read-back fixture입니다.
        """
        self._root = root
        self._results = list(results)
        self.commands: list[tuple[str, ...]] = []

    def run(
        self,
        command: Sequence[str],
        *args: object,
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        """Git은 real subprocess로 위임하고 그 밖의 command는 fixture에서 반환합니다."""
        del args, kwargs
        normalized = tuple(command)
        if normalized and normalized[0] == "git":
            if "--show-toplevel" in normalized:
                return subprocess.CompletedProcess(
                    command,
                    0,
                    f"{self._root / '.git'}\n{self._root}\ntrue\n",
                    "",
                )
            return subprocess.CompletedProcess(
                command,
                0,
                f"{self._root / '.git'}\n",
                "",
            )
        self.commands.append(normalized)
        if self._results:
            return self._results.pop(0)
        return subprocess.CompletedProcess(command, 1, "", "")


class MonitorRuntimeHandoffFixture:
    """Temporary Git worktree와 exact session workflow를 함께 준비합니다."""

    def __init__(self, *, session_id: str = "owner-thread") -> None:
        """Fixture가 사용할 runtime identity를 고정합니다.

        Args:
            session_id: Codex runtime이 제공할 exact root session identity입니다.
        """
        self._temporary = TemporaryDirectory()
        self.root = Path(self._temporary.name)
        subprocess.run(("git", "init", "-q", str(self.root)), check=True)
        self.environment: dict[str, object] = {"CODEX_THREAD_ID": session_id}
        self.workflow_id = WorkflowId("process-ticket-131")
        self.locator = SessionLocator.from_worktree(self.root)
        self.binding = RuntimeEnvironmentResolver().resolve(self.environment)
        self.handle = StateHandle.initialize(self.locator, self.binding)
        self.handle.apply(
            WorkflowStarted(
                session_id=self.handle.session_id,
                workflow_id=self.workflow_id,
                owner_actor_id=self.handle.actor_id,
                kind="process-ticket",
                goal="monitor exact PR",
                payload={
                    "skill_state": {
                        "owner_lifecycle": {
                            "state": "active",
                            "owner_session_id": session_id,
                            "source": "native-hook",
                            "transitioned_at_epoch": 100.0,
                        },
                        "monitor_mailbox": None,
                        "monitor_event_ack": None,
                    }
                },
                idempotency_key=f"fixture:{session_id}:workflow",
            )
        )

    @property
    def state_dir(self) -> Path:
        """Canonical local monitor runtime directory를 반환합니다."""
        return self.root / ".monitor-pr"

    @property
    def monitor_state(self) -> Path:
        """Canonical local monitor observation state를 반환합니다."""
        return self.state_dir / "monitor-state.json"

    def run(self) -> HandoffResultView:
        """Runtime identity와 exact workflow selector로 handoff를 실행합니다."""
        result = monitor_runtime_handoff.MonitorRuntimeHandoffApplication().run(
            (
                "--workflow-id",
                str(self.workflow_id),
                "--expected-label",
                "com.neurath.pr131.local-monitor",
                "--user-id",
                "501",
            ),
            self.environment,
            self.root,
        )
        return cast(HandoffResultView, result)

    def skill_state(self) -> dict[str, object]:
        """Exact workflow의 latest skill-state snapshot을 반환합니다."""
        return dict(SkillStateStore(self.handle, self.workflow_id).read().skill_state)

    def mapping(self, value: object, label: str) -> dict[str, object]:
        """Test assertion 전에 nested JSON object를 fail-fast 검증합니다.

        Args:
            value: Mapping이어야 하는 decoded state value입니다.
            label: Type mismatch를 설명할 assertion label입니다.
        """
        if not isinstance(value, Mapping):
            raise TypeError(f"{label} must be an object")
        return dict(value)

    def merge_skill_state(self, values: dict[str, object]) -> None:
        """Typed optimistic transaction으로 fixture state를 보강합니다.

        Args:
            values: Existing skill state에 merge할 JSON object입니다.
        """
        SkillStateStore(self.handle, self.workflow_id).update(values)

    def close(self) -> None:
        """Temporary worktree를 정리합니다."""
        self._temporary.cleanup()


class MonitorRuntimeHandoffTest(TestCase):
    """Handoff가 exact session workflow와 local runtime 하나만 사용하는지 검증합니다."""

    def test_accepts_current_runtime_resource_subscription_without_raw_paths(self) -> None:
        """Current subscription은 opaque worktree와 observation resource로 검증합니다."""
        fixture = MonitorRuntimeHandoffFixture()
        try:
            identity = monitor_runtime_handoff.WorktreeIdentityResolver().resolve(fixture.root)
            worktree_id = str(identity.worktree_id)
            fixture.merge_skill_state({
                "monitor_event_subscription": {
                    "provider": "local-pr-monitor",
                    "session_id": "owner-thread",
                    "workflow_id": str(fixture.workflow_id),
                    "runtime_id": "runtime-current",
                    "worktree_id": worktree_id,
                    "observation_resource": {
                        "kind": "monitor-observation-cache",
                        "worktree_id": worktree_id,
                    },
                    "repo": "E5presso/neurath",
                    "pr_number": 131,
                    "launcher": "launchctl",
                }
            })

            with patch.object(monitor_runtime_handoff.shutil, "which", return_value=None):
                result = fixture.run()
        finally:
            fixture.close()

        self.assertEqual(0, result.exit_code, result.stderr)

    def test_retires_obsolete_job_and_state_and_records_workflow_handoff(self) -> None:
        """Obsolete runtime 제거와 migration receipt를 exact workflow에 보존합니다."""
        fixture = MonitorRuntimeHandoffFixture()
        try:
            fixture.state_dir.mkdir()
            obsolete_plist = fixture.state_dir / "obsolete.plist"
            obsolete_plist.write_bytes(plistlib.dumps({"Label": "com.neurath.pr131.obsolete"}))
            obsolete_state = fixture.state_dir / "obsolete-state.json"
            obsolete_state.write_text(
                json.dumps({"provider": "obsolete", "last_event": {"event_id": "old"}}),
                encoding="utf-8",
            )
            router = SubprocessCommandRouter(fixture.root)
            with (
                patch.object(
                    monitor_runtime_handoff.subprocess,
                    "run",
                    side_effect=router.run,
                ),
                patch.object(
                    monitor_runtime_handoff.shutil,
                    "which",
                    return_value="/usr/bin/launchctl",
                ),
            ):
                result = fixture.run()
            skill_state = fixture.skill_state()
        finally:
            fixture.close()

        self.assertEqual(0, result.exit_code, result.stderr)
        self.assertFalse(obsolete_plist.exists())
        self.assertFalse(obsolete_state.exists())
        receipt = json.loads(result.stdout)
        self.assertEqual(["com.neurath.pr131.obsolete"], receipt["retired_labels"])
        handoff = fixture.mapping(skill_state["monitor_runtime_handoff"], "handoff")
        lifecycle = fixture.mapping(skill_state["owner_lifecycle"], "owner lifecycle")
        self.assertEqual("completed", handoff["state"])
        self.assertEqual("owner-thread", lifecycle["owner_session_id"])
        self.assertEqual(1, len(router.commands))

    def test_keeps_current_monitor_state_and_label(self) -> None:
        """Current canonical local runtime artifacts는 restart handoff에서 보존합니다."""
        fixture = MonitorRuntimeHandoffFixture()
        try:
            fixture.state_dir.mkdir()
            current_plist = fixture.state_dir / "current.plist"
            current_plist.write_bytes(plistlib.dumps({"Label": "com.neurath.pr131.local-monitor"}))
            fixture.monitor_state.write_text(
                json.dumps({"provider": "local-pr-monitor"}),
                encoding="utf-8",
            )
            router = SubprocessCommandRouter(fixture.root)
            with (
                patch.object(
                    monitor_runtime_handoff.subprocess,
                    "run",
                    side_effect=router.run,
                ),
                patch.object(monitor_runtime_handoff.shutil, "which", return_value=None),
            ):
                result = fixture.run()
                current_plist_exists = current_plist.exists()
                current_state_exists = fixture.monitor_state.exists()
        finally:
            fixture.close()

        self.assertEqual(0, result.exit_code, result.stderr)
        self.assertTrue(current_plist_exists)
        self.assertTrue(current_state_exists)
        self.assertEqual([], json.loads(result.stdout)["retired_labels"])
        self.assertEqual([], router.commands)

    def test_retires_only_exact_session_workflow_detached_runtime(self) -> None:
        """Nohup runtime은 session, workflow, route가 모두 같은 process만 종료합니다."""
        fixture = MonitorRuntimeHandoffFixture()
        try:
            fixture.merge_skill_state({
                "monitor_started": {
                    "provider": "local-pr-monitor",
                    "launcher": "nohup",
                    "session_id": "owner-thread",
                    "workflow_id": str(fixture.workflow_id),
                    "runtime_id": "runtime-exact",
                    "pid": 654,
                    "worktree": str(fixture.root.resolve()),
                    "state_path": str(fixture.monitor_state.resolve()),
                },
                "monitor_event_subscription": {
                    "provider": "local-pr-monitor",
                    "session_id": "owner-thread",
                    "thread_id": "owner-thread",
                    "workflow_id": str(fixture.workflow_id),
                    "repo": "E5presso/neurath",
                    "pr_number": 131,
                    "worktree": str(fixture.root.resolve()),
                    "state_path": str(fixture.monitor_state.resolve()),
                },
            })
            command = (
                "python local_pr_monitor.py --repo E5presso/neurath --pr-number 131 "
                f"--workflow-id {fixture.workflow_id} --runtime-id runtime-exact "
                "--launcher nohup"
            )
            ps_results: tuple[subprocess.CompletedProcess[str], ...] = (
                subprocess.CompletedProcess([], 0, command, ""),
                subprocess.CompletedProcess([], 0, command, ""),
                subprocess.CompletedProcess([], 1, "", ""),
            )
            router = SubprocessCommandRouter(fixture.root, ps_results)
            with (
                patch.object(monitor_runtime_handoff.shutil, "which", return_value=None),
                patch.object(
                    monitor_runtime_handoff.subprocess,
                    "run",
                    side_effect=router.run,
                ),
                patch.object(monitor_runtime_handoff.os, "kill") as kill,
            ):
                result = fixture.run()
        finally:
            fixture.close()

        self.assertEqual(0, result.exit_code, result.stderr)
        self.assertEqual([654], json.loads(result.stdout)["retired_detached_pids"])
        kill.assert_called_once_with(654, signal.SIGTERM)

    def test_retires_exact_orphan_without_monitor_started_receipt(self) -> None:
        """Started commit 전에 죽은 process도 exact subscription route로 회수합니다."""
        fixture = MonitorRuntimeHandoffFixture()
        try:
            fixture.merge_skill_state({
                "monitor_event_subscription": {
                    "provider": "local-pr-monitor",
                    "session_id": "owner-thread",
                    "thread_id": "owner-thread",
                    "workflow_id": str(fixture.workflow_id),
                    "runtime_id": "runtime-exact",
                    "launcher": "nohup",
                    "pid": 654,
                    "repo": "E5presso/neurath",
                    "pr_number": 131,
                    "worktree": str(fixture.root.resolve()),
                    "state_path": str(fixture.monitor_state.resolve()),
                }
            })
            command = (
                "python local_pr_monitor.py --repo E5presso/neurath --pr-number 131 "
                f"--workflow-id {fixture.workflow_id} --runtime-id runtime-exact "
                "--launcher nohup"
            )
            ps_results: tuple[subprocess.CompletedProcess[str], ...] = (
                subprocess.CompletedProcess([], 0, command, ""),
                subprocess.CompletedProcess([], 0, command, ""),
                subprocess.CompletedProcess([], 1, "", ""),
            )
            router = SubprocessCommandRouter(fixture.root, ps_results)
            with (
                patch.object(monitor_runtime_handoff.shutil, "which", return_value=None),
                patch.object(
                    monitor_runtime_handoff.subprocess,
                    "run",
                    side_effect=router.run,
                ),
                patch.object(monitor_runtime_handoff.os, "kill") as kill,
            ):
                result = fixture.run()
        finally:
            fixture.close()

        self.assertEqual(0, result.exit_code, result.stderr)
        self.assertEqual([654], json.loads(result.stdout)["retired_detached_pids"])
        kill.assert_called_once_with(654, signal.SIGTERM)

    def test_rejects_mismatched_subscription_before_any_runtime_retirement(self) -> None:
        """Persisted route가 current session/workflow와 다르면 side effect 전에 거부합니다."""
        fixture = MonitorRuntimeHandoffFixture()
        try:
            fixture.state_dir.mkdir()
            obsolete_plist = fixture.state_dir / "obsolete.plist"
            obsolete_plist.write_bytes(plistlib.dumps({"Label": "com.neurath.pr131.obsolete"}))
            fixture.merge_skill_state({
                "monitor_event_subscription": {
                    "provider": "local-pr-monitor",
                    "session_id": "foreign-session",
                    "thread_id": "foreign-session",
                    "workflow_id": str(fixture.workflow_id),
                    "worktree": str(fixture.root.resolve()),
                    "state_path": str(fixture.monitor_state.resolve()),
                }
            })
            router = SubprocessCommandRouter(fixture.root)
            with (
                patch.object(
                    monitor_runtime_handoff.subprocess,
                    "run",
                    side_effect=router.run,
                ),
                patch.object(
                    monitor_runtime_handoff.shutil,
                    "which",
                    return_value="/usr/bin/launchctl",
                ),
            ):
                result = fixture.run()
            plist_exists = obsolete_plist.exists()
        finally:
            fixture.close()

        self.assertEqual(2, result.exit_code)
        self.assertIn("session identity mismatch", result.stderr)
        self.assertTrue(plist_exists)
        self.assertEqual([], router.commands)

    def test_migrates_unacknowledged_event_once_and_preserves_owner_lifecycle(self) -> None:
        """Legacy 미ACK event는 workflow mailbox에 exact-once 이관하고 owner fence를 보존합니다."""
        fixture = MonitorRuntimeHandoffFixture()
        try:
            fixture.state_dir.mkdir()
            for name in ("legacy-a-state.json", "legacy-b-state.json"):
                (fixture.state_dir / name).write_text(
                    json.dumps({
                        "heartbeat_at_epoch": 200.0,
                        "last_seen": {"headRefOid": "a" * 40},
                        "last_event": {
                            "event_id": "legacy-event-1",
                            "monitor_event": "event",
                            "reason": "comments-changed",
                            "observation": {"headRefOid": "b" * 40},
                        },
                    }),
                    encoding="utf-8",
                )
            with patch.object(monitor_runtime_handoff.shutil, "which", return_value=None):
                result = fixture.run()
            skill_state = fixture.skill_state()
            migrated_state = json.loads(fixture.monitor_state.read_text(encoding="utf-8"))
        finally:
            fixture.close()

        self.assertEqual(0, result.exit_code, result.stderr)
        mailbox = fixture.mapping(skill_state["monitor_mailbox"], "monitor mailbox")
        pending = cast(list[dict[str, object]], mailbox["pending_events"])
        self.assertEqual(
            ["legacy-event-1"],
            [event["event_id"] for event in pending],
        )
        self.assertEqual(["legacy-event-1"], mailbox["seen_event_ids"])
        lifecycle = fixture.mapping(skill_state["owner_lifecycle"], "owner lifecycle")
        self.assertEqual("active", lifecycle["state"])
        self.assertEqual(
            {"headRefOid": "b" * 40},
            migrated_state["last_observed"]["observation"],
        )

    def test_acknowledged_and_unsafe_legacy_events_are_not_requeued(self) -> None:
        """ACK event와 aggregate 검증 불가능한 legacy delegate event는 재큐잉하지 않습니다."""
        fixture = MonitorRuntimeHandoffFixture()
        try:
            fixture.state_dir.mkdir()
            fixture.merge_skill_state({"monitor_event_ack": {"event_id": "already-acked"}})
            events = (
                ("acked-state.json", "already-acked", "comments-changed"),
                ("delegate-state.json", "legacy-delegate", "delegate-result-ready"),
                ("automatic-state.json", "legacy-auto", "review-decision-changed"),
            )
            for name, event_id, reason in events:
                (fixture.state_dir / name).write_text(
                    json.dumps({
                        "last_event": {
                            "event_id": event_id,
                            "monitor_event": "event",
                            "reason": reason,
                        }
                    }),
                    encoding="utf-8",
                )
            (fixture.state_dir / "self-acked-state.json").write_text(
                json.dumps({
                    "last_acknowledged_event_id": "legacy-self-acked",
                    "last_event": {
                        "event_id": "legacy-self-acked",
                        "monitor_event": "event",
                        "reason": "comments-changed",
                    },
                }),
                encoding="utf-8",
            )
            with patch.object(monitor_runtime_handoff.shutil, "which", return_value=None):
                result = fixture.run()
            skill_state = fixture.skill_state()
        finally:
            fixture.close()

        self.assertEqual(0, result.exit_code, result.stderr)
        receipt = json.loads(result.stdout)
        self.assertEqual([], receipt["migrated_event_ids"])
        self.assertCountEqual(
            ["legacy-delegate", "legacy-auto"],
            receipt["suppressed_legacy_event_ids"],
        )
        self.assertIsNone(skill_state["monitor_mailbox"])

    def test_state_commit_failure_preserves_legacy_state_for_retry(self) -> None:
        """Workflow CAS가 완료되지 않으면 legacy input을 삭제하지 않고 fail closed합니다."""
        fixture = MonitorRuntimeHandoffFixture()
        try:
            fixture.state_dir.mkdir()
            obsolete_state = fixture.state_dir / "legacy-state.json"
            obsolete_state.write_text(
                json.dumps({
                    "last_event": {
                        "event_id": "legacy-event-1",
                        "monitor_event": "event",
                        "reason": "comments-changed",
                    }
                }),
                encoding="utf-8",
            )
            with (
                patch.object(monitor_runtime_handoff.shutil, "which", return_value=None),
                patch.object(
                    monitor_runtime_handoff.SkillStateStore,
                    "compare_and_update",
                    side_effect=SkillStateConflict("conflict"),
                ),
            ):
                result = fixture.run()
            legacy_state_exists = obsolete_state.exists()
        finally:
            fixture.close()

        self.assertEqual(2, result.exit_code)
        self.assertTrue(legacy_state_exists)

    def test_revision_conflict_before_prepare_causes_no_external_effect(self) -> None:
        """Prepared CAS conflict는 kill, launchctl, unlink, baseline write보다 먼저 끝납니다."""
        fixture = MonitorRuntimeHandoffFixture()
        try:
            fixture.state_dir.mkdir()
            obsolete_plist = fixture.state_dir / "obsolete.plist"
            obsolete_plist.write_bytes(plistlib.dumps({"Label": "com.neurath.pr131.obsolete"}))
            obsolete_state = fixture.state_dir / "legacy-state.json"
            obsolete_state.write_text(
                json.dumps({
                    "last_seen": {"headRefOid": "a" * 40},
                    "last_event": {
                        "event_id": "legacy-event-1",
                        "monitor_event": "event",
                        "reason": "comments-changed",
                    },
                }),
                encoding="utf-8",
            )
            fixture.merge_skill_state({
                "monitor_started": {
                    "provider": "local-pr-monitor",
                    "launcher": "nohup",
                    "session_id": "owner-thread",
                    "workflow_id": str(fixture.workflow_id),
                    "runtime_id": "runtime-exact",
                    "pid": 654,
                    "worktree": str(fixture.root.resolve()),
                    "state_path": str(fixture.monitor_state.resolve()),
                },
                "monitor_event_subscription": {
                    "provider": "local-pr-monitor",
                    "session_id": "owner-thread",
                    "thread_id": "owner-thread",
                    "workflow_id": str(fixture.workflow_id),
                    "repo": "E5presso/neurath",
                    "pr_number": 131,
                    "worktree": str(fixture.root.resolve()),
                    "state_path": str(fixture.monitor_state.resolve()),
                },
            })
            command = (
                "python local_pr_monitor.py --repo E5presso/neurath --pr-number 131 "
                f"--workflow-id {fixture.workflow_id} --runtime-id runtime-exact "
                "--launcher nohup"
            )
            router = SubprocessCommandRouter(
                fixture.root,
                (subprocess.CompletedProcess([], 0, command, ""),),
            )
            with (
                patch.object(
                    monitor_runtime_handoff.subprocess,
                    "run",
                    side_effect=router.run,
                ),
                patch.object(
                    monitor_runtime_handoff.shutil,
                    "which",
                    return_value="/usr/bin/launchctl",
                ),
                patch.object(monitor_runtime_handoff.os, "kill") as kill,
                patch.object(
                    monitor_runtime_handoff.SkillStateStore,
                    "compare_and_update",
                    side_effect=SkillStateConflict("concurrent workflow commit"),
                ),
            ):
                result = fixture.run()
            plist_exists = obsolete_plist.exists()
            state_exists = obsolete_state.exists()
            baseline_exists = fixture.monitor_state.exists()
        finally:
            fixture.close()

        self.assertEqual(2, result.exit_code)
        self.assertFalse(kill.called)
        self.assertEqual(["ps"], [command[0] for command in router.commands])
        self.assertTrue(plist_exists)
        self.assertTrue(state_exists)
        self.assertFalse(baseline_exists)

    def test_replaced_plist_conflicts_before_launch_agent_unload(self) -> None:
        """Prepared plist가 교체되면 새 LaunchAgent를 unload하거나 unlink하지 않습니다."""
        fixture = MonitorRuntimeHandoffFixture()
        original_compare = monitor_runtime_handoff.SkillStateStore.compare_and_update
        compare_calls = 0
        replacement = plistlib.dumps({"Label": "com.neurath.pr131.replacement"})

        def replace_after_prepare(
            store: SkillStateStore,
            expected_revision: int,
            mutation: object,
        ) -> object:
            """Prepared commit 직후 같은 path를 다른 plist object로 교체합니다.

            Args:
                store: Exact workflow skill-state store입니다.
                expected_revision: Caller가 읽은 workflow-local revision입니다.
                mutation: Prepared 또는 completion pure mutation입니다.

            Returns:
                Original compare-and-update가 commit한 snapshot입니다.
            """
            nonlocal compare_calls
            committed = original_compare(store, expected_revision, mutation)
            compare_calls += 1
            if compare_calls == 1:
                obsolete_plist.write_bytes(replacement)
            return committed

        try:
            fixture.state_dir.mkdir()
            obsolete_plist = fixture.state_dir / "obsolete.plist"
            obsolete_plist.write_bytes(plistlib.dumps({"Label": "com.neurath.pr131.obsolete"}))
            router = SubprocessCommandRouter(fixture.root)
            with (
                patch.object(
                    monitor_runtime_handoff.SkillStateStore,
                    "compare_and_update",
                    autospec=True,
                    side_effect=replace_after_prepare,
                ),
                patch.object(
                    monitor_runtime_handoff.subprocess,
                    "run",
                    side_effect=router.run,
                ),
                patch.object(
                    monitor_runtime_handoff.shutil,
                    "which",
                    return_value="/usr/bin/launchctl",
                ),
            ):
                result = fixture.run()
            replacement_after_run = obsolete_plist.read_bytes()
            handoff = fixture.mapping(
                fixture.skill_state()["monitor_runtime_handoff"],
                "prepared handoff",
            )
        finally:
            fixture.close()

        self.assertEqual(2, result.exit_code)
        self.assertIn("external file fingerprint conflict", result.stderr)
        self.assertEqual(replacement, replacement_after_run)
        self.assertEqual([], router.commands)
        self.assertEqual("prepared", handoff["state"])

    def test_foreign_handoff_claim_is_conflict_not_idempotent_missing(self) -> None:
        """W1 claim으로 original이 없을 때 W2는 완료로 오인하지 않고 conflict합니다."""
        fixture = MonitorRuntimeHandoffFixture()
        try:
            fixture.state_dir.mkdir()
            obsolete_plist = fixture.state_dir / "obsolete.plist"
            obsolete_plist.write_bytes(plistlib.dumps({"Label": "com.neurath.pr131.obsolete"}))
            target = monitor_runtime_handoff.PreparedFileTarget.capture(
                role="launch-agent-plist",
                path=obsolete_plist,
            )
            with monitor_runtime_handoff.MonitorRuntimeCommitLock(fixture.state_dir):
                first_claim = target.claim("a" * 32)
                with self.assertRaisesRegex(
                    monitor_runtime_handoff.MonitorExternalFileConflict,
                    "foreign handoff claim",
                ):
                    target.preflight_claim("b" * 32)
            first_claim_exists = first_claim.path.exists()
            original_exists = obsolete_plist.exists()
        finally:
            fixture.close()

        self.assertTrue(first_claim_exists)
        self.assertFalse(original_exists)

    def test_missing_unclaimed_plist_is_not_reported_as_retired_label(self) -> None:
        """Prepare 뒤 사라진 plist는 success이지만 unload 증거 없이 retired로 기록하지 않습니다."""
        fixture = MonitorRuntimeHandoffFixture()
        original_compare = monitor_runtime_handoff.SkillStateStore.compare_and_update
        compare_calls = 0

        def remove_after_prepare(
            store: SkillStateStore,
            expected_revision: int,
            mutation: object,
        ) -> object:
            """Prepared commit 직후 external actor가 plist를 먼저 제거합니다.

            Args:
                store: Exact workflow skill-state store입니다.
                expected_revision: Caller가 읽은 workflow-local revision입니다.
                mutation: Prepared 또는 completion pure mutation입니다.

            Returns:
                Original compare-and-update가 commit한 snapshot입니다.
            """
            nonlocal compare_calls
            committed = original_compare(store, expected_revision, mutation)
            compare_calls += 1
            if compare_calls == 1:
                obsolete_plist.unlink()
            return committed

        try:
            fixture.state_dir.mkdir()
            obsolete_plist = fixture.state_dir / "obsolete.plist"
            obsolete_plist.write_bytes(plistlib.dumps({"Label": "com.neurath.pr131.obsolete"}))
            with (
                patch.object(
                    monitor_runtime_handoff.SkillStateStore,
                    "compare_and_update",
                    autospec=True,
                    side_effect=remove_after_prepare,
                ),
                patch.object(monitor_runtime_handoff.shutil, "which", return_value=None),
            ):
                result = fixture.run()
        finally:
            fixture.close()

        self.assertEqual(0, result.exit_code, result.stderr)
        self.assertEqual([], json.loads(result.stdout)["retired_labels"])

    def test_later_state_conflict_preflights_before_any_launch_agent_effect(self) -> None:
        """뒤 state target 충돌도 앞 LaunchAgent effect보다 먼저 전체 preflight합니다."""
        fixture = MonitorRuntimeHandoffFixture()
        original_compare = monitor_runtime_handoff.SkillStateStore.compare_and_update
        compare_calls = 0
        replacement = json.dumps({"provider": "replacement-monitor"})

        def replace_after_prepare(
            store: SkillStateStore,
            expected_revision: int,
            mutation: object,
        ) -> object:
            """Prepared commit 뒤 순서상 나중인 legacy state를 교체합니다.

            Args:
                store: Exact workflow skill-state store입니다.
                expected_revision: Caller가 읽은 workflow-local revision입니다.
                mutation: Prepared 또는 completion pure mutation입니다.

            Returns:
                Original compare-and-update가 commit한 snapshot입니다.
            """
            nonlocal compare_calls
            committed = original_compare(store, expected_revision, mutation)
            compare_calls += 1
            if compare_calls == 1:
                obsolete_state.write_text(replacement, encoding="utf-8")
            return committed

        try:
            fixture.state_dir.mkdir()
            obsolete_plist = fixture.state_dir / "obsolete.plist"
            obsolete_plist.write_bytes(plistlib.dumps({"Label": "com.neurath.pr131.obsolete"}))
            obsolete_state = fixture.state_dir / "legacy-state.json"
            obsolete_state.write_text(
                json.dumps({"last_seen": {"headRefOid": "a" * 40}}),
                encoding="utf-8",
            )
            router = SubprocessCommandRouter(fixture.root)
            with (
                patch.object(
                    monitor_runtime_handoff.SkillStateStore,
                    "compare_and_update",
                    autospec=True,
                    side_effect=replace_after_prepare,
                ),
                patch.object(
                    monitor_runtime_handoff.subprocess,
                    "run",
                    side_effect=router.run,
                ),
                patch.object(
                    monitor_runtime_handoff.shutil,
                    "which",
                    return_value="/usr/bin/launchctl",
                ),
            ):
                result = fixture.run()
            plist_exists = obsolete_plist.exists()
            state_after_run = obsolete_state.read_text(encoding="utf-8")
            baseline_exists = fixture.monitor_state.exists()
        finally:
            fixture.close()

        self.assertEqual(2, result.exit_code)
        self.assertIn("external file fingerprint conflict", result.stderr)
        self.assertTrue(plist_exists)
        self.assertEqual(replacement, state_after_run)
        self.assertFalse(baseline_exists)
        self.assertEqual([], router.commands)

    def test_replaced_state_lock_is_never_unlinked_without_a_fingerprint(self) -> None:
        """Unplanned state lock sidecar는 replacement 여부와 무관하게 삭제하지 않습니다."""
        fixture = MonitorRuntimeHandoffFixture()
        original_compare = monitor_runtime_handoff.SkillStateStore.compare_and_update
        compare_calls = 0
        replacement = "replacement-lock-owner\n"

        def replace_after_prepare(
            store: SkillStateStore,
            expected_revision: int,
            mutation: object,
        ) -> object:
            """Prepared commit 뒤 legacy sidecar lock object를 교체합니다.

            Args:
                store: Exact workflow skill-state store입니다.
                expected_revision: Caller가 읽은 workflow-local revision입니다.
                mutation: Prepared 또는 completion pure mutation입니다.

            Returns:
                Original compare-and-update가 commit한 snapshot입니다.
            """
            nonlocal compare_calls
            committed = original_compare(store, expected_revision, mutation)
            compare_calls += 1
            if compare_calls == 1:
                legacy_lock.write_text(replacement, encoding="utf-8")
            return committed

        try:
            fixture.state_dir.mkdir()
            obsolete_state = fixture.state_dir / "legacy-state.json"
            obsolete_state.write_text("{}", encoding="utf-8")
            legacy_lock = obsolete_state.with_name(f"{obsolete_state.name}.lock")
            legacy_lock.write_text("original-lock-owner\n", encoding="utf-8")
            with (
                patch.object(
                    monitor_runtime_handoff.SkillStateStore,
                    "compare_and_update",
                    autospec=True,
                    side_effect=replace_after_prepare,
                ),
                patch.object(monitor_runtime_handoff.shutil, "which", return_value=None),
            ):
                result = fixture.run()
            state_exists = obsolete_state.exists()
            lock_after_run = legacy_lock.read_text(encoding="utf-8")
            baseline_exists = fixture.monitor_state.exists()
        finally:
            fixture.close()

        self.assertEqual(0, result.exit_code, result.stderr)
        self.assertFalse(state_exists)
        self.assertEqual(replacement, lock_after_run)
        self.assertTrue(baseline_exists)

    def test_symlinked_state_conflicts_without_touching_replacement_target(self) -> None:
        """Prepared regular file이 symlink가 되면 link와 destination을 모두 보존합니다."""
        fixture = MonitorRuntimeHandoffFixture()
        original_compare = monitor_runtime_handoff.SkillStateStore.compare_and_update
        compare_calls = 0

        def replace_after_prepare(
            store: SkillStateStore,
            expected_revision: int,
            mutation: object,
        ) -> object:
            """Prepared commit 뒤 legacy path를 외부 regular file symlink로 바꿉니다.

            Args:
                store: Exact workflow skill-state store입니다.
                expected_revision: Caller가 읽은 workflow-local revision입니다.
                mutation: Prepared 또는 completion pure mutation입니다.

            Returns:
                Original compare-and-update가 commit한 snapshot입니다.
            """
            nonlocal compare_calls
            committed = original_compare(store, expected_revision, mutation)
            compare_calls += 1
            if compare_calls == 1:
                obsolete_state.unlink()
                obsolete_state.symlink_to(replacement_target)
            return committed

        try:
            fixture.state_dir.mkdir()
            obsolete_state = fixture.state_dir / "legacy-state.json"
            obsolete_state.write_text("{}", encoding="utf-8")
            replacement_target = fixture.root / "replacement-state.json"
            replacement_target.write_text(
                json.dumps({"provider": "replacement-monitor"}),
                encoding="utf-8",
            )
            with (
                patch.object(
                    monitor_runtime_handoff.SkillStateStore,
                    "compare_and_update",
                    autospec=True,
                    side_effect=replace_after_prepare,
                ),
                patch.object(monitor_runtime_handoff.shutil, "which", return_value=None),
            ):
                result = fixture.run()
            remains_symlink = obsolete_state.is_symlink()
            replacement_payload = replacement_target.read_text(encoding="utf-8")
        finally:
            fixture.close()

        self.assertEqual(2, result.exit_code)
        self.assertIn("external file fingerprint conflict", result.stderr)
        self.assertTrue(remains_symlink)
        self.assertEqual(
            json.dumps({"provider": "replacement-monitor"}),
            replacement_payload,
        )

    def test_baseline_no_replace_preserves_state_created_during_atomic_publish(self) -> None:
        """Baseline atomic create 경쟁에서 먼저 생긴 canonical state를 덮어쓰지 않습니다."""
        fixture = MonitorRuntimeHandoffFixture()
        original_link = monitor_runtime_handoff.os.link
        fresh_payload = {"provider": "fresh-current-monitor", "revision": 7}
        injected = False

        def create_current_before_link(source: str, destination: str) -> None:
            """Baseline no-replace link 직전에 경쟁 writer의 current state를 생성합니다.

            Args:
                source: Fsync가 끝난 prepared temporary baseline path입니다.
                destination: Canonical monitor state path입니다.

            Raises:
                FileExistsError: 경쟁 writer가 destination을 먼저 만들었음을 재현합니다.
            """
            nonlocal injected
            destination_path = Path(destination)
            if destination_path.resolve() == fixture.monitor_state.resolve() and not injected:
                injected = True
                destination_path.write_text(json.dumps(fresh_payload), encoding="utf-8")
            original_link(source, destination)

        try:
            fixture.state_dir.mkdir()
            obsolete_state = fixture.state_dir / "legacy-state.json"
            obsolete_state.write_text(
                json.dumps({"last_seen": {"headRefOid": "a" * 40}}),
                encoding="utf-8",
            )
            with (
                patch.object(monitor_runtime_handoff.shutil, "which", return_value=None),
                patch.object(
                    monitor_runtime_handoff.os,
                    "link",
                    side_effect=create_current_before_link,
                ),
            ):
                result = fixture.run()
            current_payload = json.loads(fixture.monitor_state.read_text(encoding="utf-8"))
        finally:
            fixture.close()

        self.assertEqual(0, result.exit_code, result.stderr)
        self.assertTrue(injected)
        self.assertEqual(fresh_payload, current_payload)

    def test_commit_lock_is_released_before_process_and_launchctl_io(self) -> None:
        """Fingerprint claim mutex 안에서는 timeout 없는 ps, wait, launchctl을 실행하지 않습니다."""
        fixture = MonitorRuntimeHandoffFixture()
        lock_depth = 0
        original_enter = monitor_runtime_handoff.MonitorRuntimeCommitLock.__enter__
        original_exit = monitor_runtime_handoff.MonitorRuntimeCommitLock.__exit__

        def tracked_enter(
            lock: monitor_runtime_handoff.MonitorRuntimeCommitLock,
        ) -> object:
            """Real advisory lock을 잡은 뒤 test-visible depth를 올립니다.

            Args:
                lock: Handoff service가 사용하는 runtime-directory commit lock입니다.

            Returns:
                Original context-manager enter 결과입니다.
            """
            nonlocal lock_depth
            entered = original_enter(lock)
            lock_depth += 1
            return entered

        def tracked_exit(
            lock: monitor_runtime_handoff.MonitorRuntimeCommitLock,
            exception_type: object,
            exception: object,
            traceback: object,
        ) -> None:
            """Test-visible depth와 real advisory lock을 함께 해제합니다.

            Args:
                lock: Handoff service가 사용하는 runtime-directory commit lock입니다.
                exception_type: Context body exception type입니다.
                exception: Context body exception instance입니다.
                traceback: Context body traceback입니다.
            """
            nonlocal lock_depth
            original_exit(lock, exception_type, exception, traceback)
            lock_depth -= 1

        def kill_outside_lock(pid: int, requested_signal: signal.Signals) -> None:
            """Detached process signal이 commit lock 밖인지 assertion합니다.

            Args:
                pid: Prepared detached process ID입니다.
                requested_signal: Retirement signal입니다.
            """
            self.assertEqual(0, lock_depth)
            self.assertEqual((654, signal.SIGTERM), (pid, requested_signal))

        try:
            fixture.state_dir.mkdir()
            obsolete_plist = fixture.state_dir / "obsolete.plist"
            obsolete_plist.write_bytes(plistlib.dumps({"Label": "com.neurath.pr131.obsolete"}))
            fixture.merge_skill_state({
                "monitor_started": {
                    "provider": "local-pr-monitor",
                    "launcher": "nohup",
                    "session_id": "owner-thread",
                    "workflow_id": str(fixture.workflow_id),
                    "runtime_id": "runtime-exact",
                    "pid": 654,
                    "worktree": str(fixture.root.resolve()),
                    "state_path": str(fixture.monitor_state.resolve()),
                },
                "monitor_event_subscription": {
                    "provider": "local-pr-monitor",
                    "session_id": "owner-thread",
                    "thread_id": "owner-thread",
                    "workflow_id": str(fixture.workflow_id),
                    "repo": "E5presso/neurath",
                    "pr_number": 131,
                    "worktree": str(fixture.root.resolve()),
                    "state_path": str(fixture.monitor_state.resolve()),
                },
            })
            command = (
                "python local_pr_monitor.py --repo E5presso/neurath --pr-number 131 "
                f"--workflow-id {fixture.workflow_id} --runtime-id runtime-exact "
                "--launcher nohup"
            )
            router = SubprocessCommandRouter(
                fixture.root,
                (
                    subprocess.CompletedProcess([], 0, command, ""),
                    subprocess.CompletedProcess([], 0, command, ""),
                    subprocess.CompletedProcess([], 1, "", ""),
                    subprocess.CompletedProcess([], 1, "", ""),
                ),
            )

            def run_outside_lock(
                process_command: Sequence[str],
                *args: object,
                **kwargs: object,
            ) -> subprocess.CompletedProcess[str]:
                """모든 subprocess call이 commit mutex 밖인지 assertion합니다.

                Args:
                    process_command: Git, ps 또는 launchctl argv입니다.
                    args: Subprocess compatibility positional arguments입니다.
                    kwargs: Subprocess compatibility keyword arguments입니다.

                Returns:
                    Existing fixture router의 deterministic process result입니다.
                """
                if process_command and process_command[0] != "git":
                    self.assertEqual(0, lock_depth)
                return router.run(process_command, *args, **kwargs)

            with (
                patch.object(
                    monitor_runtime_handoff.MonitorRuntimeCommitLock,
                    "__enter__",
                    autospec=True,
                    side_effect=tracked_enter,
                ),
                patch.object(
                    monitor_runtime_handoff.MonitorRuntimeCommitLock,
                    "__exit__",
                    autospec=True,
                    side_effect=tracked_exit,
                ),
                patch.object(
                    monitor_runtime_handoff.subprocess,
                    "run",
                    side_effect=run_outside_lock,
                ),
                patch.object(
                    monitor_runtime_handoff.shutil,
                    "which",
                    return_value="/usr/bin/launchctl",
                ),
                patch.object(
                    monitor_runtime_handoff.os,
                    "kill",
                    side_effect=kill_outside_lock,
                ),
            ):
                result = fixture.run()
        finally:
            fixture.close()

        self.assertEqual(0, result.exit_code, result.stderr)
        self.assertEqual(0, lock_depth)

    def test_new_invocation_resumes_prepared_handoff_after_retirement_crash(self) -> None:
        """Retirement 뒤 completion conflict는 새 invocation이 같은 prepared intent로 잇습니다."""
        fixture = MonitorRuntimeHandoffFixture()
        original_compare = monitor_runtime_handoff.SkillStateStore.compare_and_update
        compare_calls = 0

        def conflict_on_completion(
            store: SkillStateStore,
            expected_revision: int,
            mutation: object,
        ) -> object:
            """두 번째 explicit CAS만 충돌시켜 retirement 이후 crash를 재현합니다.

            Args:
                store: Exact workflow에 bound된 skill-state store입니다.
                expected_revision: Caller가 읽은 workflow-local revision입니다.
                mutation: Prepared 또는 completion pure state mutation입니다.

            Returns:
                첫 prepared CAS가 commit한 immutable workflow snapshot입니다.

            Raises:
                SkillStateConflict: 두 번째 completion CAS에서 의도적으로 발생합니다.
            """
            nonlocal compare_calls
            compare_calls += 1
            if compare_calls == 2:
                raise SkillStateConflict("completion conflict")
            return original_compare(store, expected_revision, mutation)

        try:
            fixture.state_dir.mkdir()
            obsolete_plist = fixture.state_dir / "obsolete.plist"
            obsolete_plist.write_bytes(plistlib.dumps({"Label": "com.neurath.pr131.obsolete"}))
            obsolete_state = fixture.state_dir / "legacy-state.json"
            obsolete_state.write_text(
                json.dumps({
                    "last_seen": {"headRefOid": "a" * 40},
                    "last_event": {
                        "event_id": "legacy-event-1",
                        "monitor_event": "event",
                        "reason": "comments-changed",
                    },
                }),
                encoding="utf-8",
            )
            fixture.merge_skill_state({
                "monitor_started": {
                    "provider": "local-pr-monitor",
                    "launcher": "nohup",
                    "session_id": "owner-thread",
                    "workflow_id": str(fixture.workflow_id),
                    "runtime_id": "runtime-exact",
                    "pid": 654,
                    "worktree": str(fixture.root.resolve()),
                    "state_path": str(fixture.monitor_state.resolve()),
                },
                "monitor_event_subscription": {
                    "provider": "local-pr-monitor",
                    "session_id": "owner-thread",
                    "thread_id": "owner-thread",
                    "workflow_id": str(fixture.workflow_id),
                    "repo": "E5presso/neurath",
                    "pr_number": 131,
                    "worktree": str(fixture.root.resolve()),
                    "state_path": str(fixture.monitor_state.resolve()),
                },
            })
            command = (
                "python local_pr_monitor.py --repo E5presso/neurath --pr-number 131 "
                f"--workflow-id {fixture.workflow_id} --runtime-id runtime-exact "
                "--launcher nohup"
            )
            router = SubprocessCommandRouter(
                fixture.root,
                (
                    subprocess.CompletedProcess([], 0, command, ""),
                    subprocess.CompletedProcess([], 0, command, ""),
                    subprocess.CompletedProcess([], 1, "", ""),
                    subprocess.CompletedProcess([], 1, "", ""),
                ),
            )
            with (
                patch.object(monitor_runtime_handoff.shutil, "which", return_value=None),
                patch.object(
                    monitor_runtime_handoff.subprocess,
                    "run",
                    side_effect=router.run,
                ),
                patch.object(monitor_runtime_handoff.os, "kill") as kill,
            ):
                with patch.object(
                    monitor_runtime_handoff.SkillStateStore,
                    "compare_and_update",
                    autospec=True,
                    side_effect=conflict_on_completion,
                ):
                    interrupted = fixture.run()
                plist_exists_after_interrupt = obsolete_plist.exists()
                state_exists_after_interrupt = obsolete_state.exists()
                prepared = fixture.mapping(
                    fixture.skill_state()["monitor_runtime_handoff"],
                    "prepared handoff",
                )
                planned_detached = cast(
                    list[dict[str, object]],
                    prepared["planned_detached_targets"],
                )
                planned_launch_agents = cast(
                    list[dict[str, object]],
                    prepared["planned_launch_agents"],
                )
                planned_state_targets = cast(
                    list[dict[str, object]],
                    prepared["planned_state_targets"],
                )
                handoff_id = prepared["handoff_id"]
                resumed = fixture.run()
                completed = fixture.mapping(
                    fixture.skill_state()["monitor_runtime_handoff"],
                    "completed handoff",
                )
        finally:
            fixture.close()

        self.assertEqual(2, interrupted.exit_code)
        self.assertFalse(plist_exists_after_interrupt)
        self.assertFalse(state_exists_after_interrupt)
        self.assertEqual("prepared", prepared["state"])
        self.assertEqual([654], [target["pid"] for target in planned_detached])
        self.assertEqual(
            ["com.neurath.pr131.obsolete"],
            [target["label"] for target in planned_launch_agents],
        )
        plist_target = fixture.mapping(
            planned_launch_agents[0]["plist_target"],
            "planned plist fingerprint",
        )
        self.assertIs(plist_target["regular_file"], True)
        self.assertEqual(64, len(cast(str, plist_target["sha256"])))
        self.assertEqual("legacy-state", planned_state_targets[0]["role"])
        self.assertIs(planned_state_targets[0]["regular_file"], True)
        self.assertEqual(64, len(cast(str, planned_state_targets[0]["sha256"])))
        self.assertEqual([str(obsolete_state.resolve())], prepared["planned_state_paths"])
        self.assertEqual(str(obsolete_state.resolve()), prepared["baseline_source_path"])
        self.assertIsInstance(prepared["baseline_payload"], Mapping)
        self.assertEqual(0, resumed.exit_code, resumed.stderr)
        self.assertEqual(handoff_id, completed["handoff_id"])
        self.assertEqual("completed", completed["state"])
        kill.assert_called_once_with(654, signal.SIGTERM)

    def test_new_invocation_adopts_durable_file_claims_after_abrupt_stop(self) -> None:
        """Claim 뒤 process crash도 같은 prepared plan이 claim을 재사용해 완료합니다."""

        class SimulatedProcessStop(BaseException):
            """Application error handling을 건너뛰는 abrupt process termination입니다."""

        fixture = MonitorRuntimeHandoffFixture()
        try:
            fixture.state_dir.mkdir()
            obsolete_plist = fixture.state_dir / "obsolete.plist"
            obsolete_plist.write_bytes(plistlib.dumps({"Label": "com.neurath.pr131.obsolete"}))
            obsolete_state = fixture.state_dir / "legacy-state.json"
            obsolete_state.write_text("{}", encoding="utf-8")
            with (
                patch.object(monitor_runtime_handoff.shutil, "which", return_value=None),
                patch.object(
                    monitor_runtime_handoff.MonitorRuntimeInventory,
                    "retire_launch_agents",
                    side_effect=SimulatedProcessStop("stopped after file claim"),
                ),
                self.assertRaises(SimulatedProcessStop),
            ):
                fixture.run()
            prepared = fixture.mapping(
                fixture.skill_state()["monitor_runtime_handoff"],
                "prepared handoff",
            )
            claims_after_stop = tuple(fixture.state_dir.glob("*.claimed"))
            originals_after_stop = (obsolete_plist.exists(), obsolete_state.exists())

            with patch.object(monitor_runtime_handoff.shutil, "which", return_value=None):
                resumed = fixture.run()
            completed = fixture.mapping(
                fixture.skill_state()["monitor_runtime_handoff"],
                "completed handoff",
            )
            claims_after_resume = tuple(fixture.state_dir.glob("*.claimed"))
        finally:
            fixture.close()

        self.assertEqual("prepared", prepared["state"])
        self.assertEqual(2, len(claims_after_stop))
        self.assertEqual((False, False), originals_after_stop)
        self.assertEqual(0, resumed.exit_code, resumed.stderr)
        self.assertEqual(prepared["handoff_id"], completed["handoff_id"])
        self.assertEqual("completed", completed["state"])
        self.assertEqual((), claims_after_resume)

    def test_loaded_obsolete_launch_agent_preserves_all_retirement_inputs(self) -> None:
        """Launchd read-back이 old label 생존을 보이면 plist와 state를 보존합니다."""
        fixture = MonitorRuntimeHandoffFixture()
        try:
            fixture.state_dir.mkdir()
            obsolete_plist = fixture.state_dir / "obsolete.plist"
            obsolete_plist.write_bytes(plistlib.dumps({"Label": "com.neurath.pr131.obsolete"}))
            obsolete_state = fixture.state_dir / "legacy-state.json"
            obsolete_state.write_text("{}", encoding="utf-8")
            results: tuple[subprocess.CompletedProcess[str], ...] = (
                subprocess.CompletedProcess([], 0, "still loaded", ""),
                subprocess.CompletedProcess([], 1, "", "bootout failed"),
                subprocess.CompletedProcess([], 1, "", "remove failed"),
                subprocess.CompletedProcess([], 0, "still loaded", ""),
            )
            router = SubprocessCommandRouter(fixture.root, results)
            with (
                patch.object(
                    monitor_runtime_handoff.shutil,
                    "which",
                    return_value="/usr/bin/launchctl",
                ),
                patch.object(
                    monitor_runtime_handoff.subprocess,
                    "run",
                    side_effect=router.run,
                ),
            ):
                result = fixture.run()
            plist_exists = obsolete_plist.exists()
            state_exists = obsolete_state.exists()
        finally:
            fixture.close()

        self.assertEqual(2, result.exit_code)
        self.assertIn("obsolete monitor runtime is still loaded", result.stderr)
        self.assertTrue(plist_exists)
        self.assertTrue(state_exists)

    def test_missing_runtime_identity_and_unknown_workflow_fail_closed(self) -> None:
        """Ambient path scan 없이 runtime identity와 exact workflow 모두를 필수로 요구합니다."""
        fixture = MonitorRuntimeHandoffFixture()
        try:
            application = monitor_runtime_handoff.MonitorRuntimeHandoffApplication()
            missing_identity = application.run(
                (
                    "--workflow-id",
                    str(fixture.workflow_id),
                    "--expected-label",
                    "com.neurath.pr131.local-monitor",
                    "--user-id",
                    "501",
                ),
                {},
                fixture.root,
            )
            unknown_workflow = application.run(
                (
                    "--workflow-id",
                    "process-ticket-foreign",
                    "--expected-label",
                    "com.neurath.pr131.local-monitor",
                    "--user-id",
                    "501",
                ),
                fixture.environment,
                fixture.root,
            )
        finally:
            fixture.close()

        self.assertEqual(2, missing_identity.exit_code)
        self.assertIn("runtime-owned session identity is unavailable", missing_identity.stderr)
        self.assertEqual(2, unknown_workflow.exit_code)
        self.assertIn("workflow is missing", unknown_workflow.stderr)

    def test_prepared_mutation_is_pure_and_keeps_one_captured_timestamp(self) -> None:
        """Optimistic retry는 외부 시각을 다시 읽지 않고 concurrent sibling state를 보존합니다."""
        mutation = monitor_runtime_handoff.MonitorHandoffPreparedMutation(
            session_id="owner-thread",
            workflow_id="process-ticket-131",
            worktree="/tmp/worktree",
            prepared_at="2026-08-04T00:00:00+00:00",
            mailbox_updated_at_epoch=123.0,
            receipt={"state": "prepared", "handoff_id": "handoff-1"},
            migrated_events=(
                {
                    "event_id": "event-1",
                    "monitor_event": "event",
                    "reason": "comments-changed",
                },
            ),
        )
        current = {
            "owner_lifecycle": {
                "state": "idle",
                "owner_session_id": "owner-thread",
            },
            "monitor_mailbox": None,
            "monitor_event_ack": None,
        }

        first = mutation(current)
        second = mutation({**current, "concurrent_evidence": {"kept": True}})

        self.assertEqual(first["monitor_runtime_handoff"], second["monitor_runtime_handoff"])
        second_mailbox = cast(Mapping[str, object], second["monitor_mailbox"])
        self.assertEqual(123.0, second_mailbox["updated_at_epoch"])
        self.assertEqual({"kept": True}, second["concurrent_evidence"])
        self.assertIsNone(current["monitor_mailbox"])

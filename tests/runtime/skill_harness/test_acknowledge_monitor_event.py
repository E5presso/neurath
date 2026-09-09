"""Monitor event ACK의 live-readback/CAS 경계를 검증합니다."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from collections.abc import Mapping
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Protocol
from unittest import TestCase, mock

from scripts.agent_harness.session_kernel import (
    ActorId,
    ResumeId,
    SessionId,
    SessionKernel,
    SessionLocator,
    SessionRuntime,
    SessionStarted,
    WorkflowId,
    WorkflowStarted,
    WorktreeId,
)
from scripts.agent_harness.skill_state_store import SkillStateStore
from scripts.agent_harness.state_handle import RuntimeIdentityBinding, StateHandle
from scripts.agent_harness.worktree_registry import CanonicalWorktreeIdentity

ROOT = Path(__file__).parents[3]
SCRIPT = ROOT / ".agents/skills/monitor-pr/scripts/acknowledge_event.py"
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("acknowledge_event", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
acknowledge_event = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = acknowledge_event
SPEC.loader.exec_module(acknowledge_event)


def mapping(value: object, label: str) -> Mapping[str, object]:
    """Test fixture object를 checked mapping으로 좁힙니다.

    Args:
        value: Canonical state에서 object shape를 기대하는 값입니다.
        label: Shape 오류에서 fixture 위치를 식별할 이름입니다.

    Returns:
        Object shape가 검증된 read-only mapping view입니다.

    Raises:
        TypeError: Fixture 값이 JSON object가 아닐 때 발생합니다.
    """
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be an object")
    return value


class Acknowledger(Protocol):
    """Dynamic-loaded ACK application의 test-facing port입니다."""

    def acknowledge(self) -> dict[str, object]:
        """Canonical ACK receipt를 반환합니다.

        Returns:
            Exact workflow CAS가 저장한 typed acknowledgement입니다.
        """


class MonitorAcknowledgementFixture:
    """Canonical session/workflow와 process-local observation cache를 구성합니다."""

    def __init__(self, root: Path) -> None:
        """Exact session, workflow, route와 local observation fixture를 엽니다.

        Args:
            root: Session control state와 local observation을 격리할 임시 root입니다.
        """
        self.worktree = root
        subprocess.run(("git", "init", "-q", str(root)), check=True)
        self.locator = SessionLocator.from_worktree(root)
        self.session_id = SessionId("session")
        self.actor_id = ActorId("codex:session:session")
        self.workflow_id = WorkflowId("process-ticket-42")
        self.runtime_id = "runtime-a"
        self.binding = RuntimeIdentityBinding(
            runtime=SessionRuntime.CODEX,
            session_id=self.session_id,
            actor_id=self.actor_id,
            root_actor_id=self.actor_id,
        )
        self.resources = acknowledge_event.MonitorRuntimeResources(
            binding=self.binding,
            worktree=CanonicalWorktreeIdentity(
                worktree_id=WorktreeId("fixture-worktree"),
                path=self.worktree.resolve(),
                repository_control_root=root.resolve(),
            ),
        )
        kernel = SessionKernel(self.locator)
        kernel.apply(
            SessionStarted(
                session_id=self.session_id,
                resume_id=ResumeId("session"),
                runtime=SessionRuntime.CODEX,
                root_actor_id=self.actor_id,
                idempotency_key="fixture:session-start",
            )
        )
        self.handle = StateHandle.attach(
            self.locator,
            self.binding,
        )
        self.handle.apply(
            WorkflowStarted(
                session_id=self.session_id,
                workflow_id=self.workflow_id,
                owner_actor_id=self.actor_id,
                kind="process-ticket",
                goal="fixture",
                payload={
                    "skill_state": {
                        "monitor_mailbox": {
                            "pending_events": [],
                            "seen_event_ids": [],
                            "active_claim": None,
                            "updated_at_epoch": 0.0,
                        },
                        "monitor_event_subscription": self.route(),
                    }
                },
                idempotency_key="fixture:workflow-start",
            )
        )
        self.store = SkillStateStore(self.handle, self.workflow_id)
        self.observations = acknowledge_event.MonitorObservationStore(
            self.resources.observation_path
        )

    def route(self) -> dict[str, object]:
        """Canonical workflow에 저장할 exact monitor route를 반환합니다.

        Returns:
            Session, workflow, runtime, worktree, observation resource가 결속된 route입니다.
        """
        return {
            "repo": "E5presso/neurath",
            "pr_number": 42,
            "session_id": str(self.session_id),
            "workflow_id": str(self.workflow_id),
            "runtime_id": self.runtime_id,
            "worktree_id": self.resources.worktree_id,
            "observation_resource": self.resources.observation_resource(),
        }

    def set_route(self, route: Mapping[str, object] | None) -> None:
        """Expected route 변경을 canonical workflow revision으로 기록합니다.

        Args:
            route: 교체할 subscription이며 `None`이면 route 자체를 제거합니다.
        """

        def mutation(current: Mapping[str, object]) -> Mapping[str, object]:
            """Unrelated workflow evidence를 보존하며 route만 교체합니다.

            Args:
                current: CAS update가 제공한 current skill state입니다.

            Returns:
                Requested subscription replacement가 반영된 다음 state입니다.
            """
            updated = dict(current)
            if route is None:
                updated.pop("monitor_event_subscription", None)
            else:
                updated["monitor_event_subscription"] = dict(route)
            return updated

        self.store.update(mutation)

    def stage(self, event: Mapping[str, object], *, active: bool = False) -> None:
        """Canonical mailbox와 local observation에 같은 event를 배치합니다.

        Args:
            event: ACK 선택에 사용할 exact monitor occurrence입니다.
            active: Event를 pending queue 대신 active claim에 넣을지 결정합니다.
        """
        event_payload = dict(event)

        def mutation(current: Mapping[str, object]) -> Mapping[str, object]:
            """현재 mailbox에 requested event occurrence를 pure하게 배치합니다.

            Args:
                current: CAS update가 제공한 current skill state입니다.

            Returns:
                Pending 또는 active occurrence가 반영된 다음 state입니다.
            """
            mailbox = dict(mapping(current.get("monitor_mailbox"), "monitor mailbox"))
            mailbox["seen_event_ids"] = [event_payload["event_id"]]
            if active:
                mailbox["active_claim"] = {
                    "claim_id": "claim-1",
                    "event": event_payload,
                }
                mailbox["pending_events"] = []
            else:
                mailbox["active_claim"] = None
                mailbox["pending_events"] = [event_payload]
            return {**current, "monitor_mailbox": mailbox}

        self.store.update(mutation)
        self.write_observation(event_payload)

    def write_observation(self, event: Mapping[str, object]) -> None:
        """Expected route producer identity와 latest event를 local cache에 기록합니다.

        Args:
            event: Monitor process가 마지막으로 관측했다고 가정할 occurrence입니다.
        """
        self.observations.write({
            "provider": "local-pr-monitor",
            "repo": "E5presso/neurath",
            "pr_number": 42,
            "session_id": str(self.session_id),
            "workflow_id": str(self.workflow_id),
            "runtime_id": self.runtime_id,
            "worktree_id": self.resources.worktree_id,
            "last_event": dict(event),
        })

    def acknowledger(
        self,
        event_id: str | None = None,
    ) -> Acknowledger:
        """Fixture identity에 attach된 exact ACK application을 반환합니다.

        Args:
            event_id: 명시하면 해당 mailbox occurrence만 선택합니다.

        Returns:
            Canonical workflow와 derived resources에 결속된 ACK port입니다.
        """
        return acknowledge_event.MonitorEventAcknowledger(
            self.handle,
            self.workflow_id,
            self.resources,
            event_id=event_id,
        )


class AcknowledgeMonitorEventTest(TestCase):
    """외부 I/O와 optimistic commit 사이의 stale evidence 적용을 차단합니다."""

    def setUp(self) -> None:
        """각 case에 독립 session/workflow와 observation resource를 제공합니다."""
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.fixture = MonitorAcknowledgementFixture(Path(self.temporary_directory.name))

    def test_records_matching_event_with_evidence_in_exact_workflow(self) -> None:
        """Matching active occurrence만 canonical ACK로 소비하는지 검증합니다."""
        event = {
            "monitor_event": "event",
            "event_id": "event-123",
            "reason": "ci-failed",
        }
        self.fixture.stage(event, active=True)
        with mock.patch.object(
            acknowledge_event.MonitorEventEvidenceCollector,
            "collect",
            return_value=["ci_readback:failedChecks=0"],
        ):
            result = self.fixture.acknowledger().acknowledge()

        saved = self.fixture.store.read().skill_state
        acknowledgement = mapping(saved["monitor_event_ack"], "acknowledgement")
        mailbox = mapping(saved["monitor_mailbox"], "monitor mailbox")
        self.assertEqual("event-123", result["event_id"])
        self.assertEqual("event-123", acknowledgement["event_id"])
        self.assertEqual([], mailbox["pending_events"])
        local = self.fixture.observations.read()
        self.assertNotIn("last_acknowledged_event_id", local)
        self.assertEqual("event-123", mapping(local["last_event"], "last event")["event_id"])

    def test_external_readback_conflict_never_applies_stale_ack(self) -> None:
        """External read-back 중 revision conflict가 stale ACK를 남기지 않는지 검증합니다."""
        event = {
            "monitor_event": "event",
            "event_id": "event-123",
            "reason": "ci-failed",
        }
        self.fixture.stage(event, active=True)

        def concurrent_readback(*_args: object, **_kwargs: object) -> list[str]:
            """External read-back 시점에 competing workflow revision을 만듭니다.

            Args:
                _args: Collector call과 같은 positional arguments입니다.
                _kwargs: Collector call과 같은 keyword arguments입니다.

            Returns:
                ACK 의미 자체는 유효한 live CI evidence입니다.
            """
            self.fixture.store.update({"concurrent_change": True})
            return ["ci_readback:failedChecks=0"]

        with (
            mock.patch.object(
                acknowledge_event.MonitorEventEvidenceCollector,
                "collect",
                side_effect=concurrent_readback,
            ),
            self.assertRaisesRegex(
                acknowledge_event.MonitorAcknowledgementConflict,
                "rerun the command",
            ),
        ):
            self.fixture.acknowledger().acknowledge()

        self.assertNotIn("monitor_event_ack", self.fixture.store.read().skill_state)

    def test_exact_pending_event_can_be_acknowledged_after_local_latest_advances(self) -> None:
        """Explicit event ID가 local latest보다 canonical pending occurrence를 우선합니다."""
        pending = {
            "monitor_event": "event",
            "event_id": "event-pending",
            "reason": "merge-dirty",
        }
        self.fixture.stage(pending)
        self.fixture.write_observation({
            "monitor_event": "event",
            "event_id": "event-later",
            "reason": "ci-failed",
        })
        with mock.patch.object(
            acknowledge_event.MonitorEventEvidenceCollector,
            "collect",
            return_value=["merge_readback:mergeState=CLEAN"],
        ):
            result = self.fixture.acknowledger("event-pending").acknowledge()

        self.assertEqual("event-pending", result["event_id"])

    def test_records_external_review_wait_without_consuming_event(self) -> None:
        """Reviewer-owned wait는 event를 소비하지 않고 typed wait만 기록합니다."""
        event = {
            "monitor_event": "event",
            "event_id": "review-event",
            "reason": "comments-changed",
        }
        self.fixture.stage(event, active=True)
        evidence = [
            "collect_comments:TOTAL=0",
            "collect_comments:UNRESOLVED_THREADS_COUNT=2",
            "wait_readback:mergeState=CLEAN",
            "wait_readback:reviewDecision=REVIEW_REQUIRED",
            "wait_readback:failedChecks=0",
            "wait_readback:pendingChecks=0",
            "wait_readback:headRefOid=abc",
            "wait_readback:unresolvedReviewThreads=2",
        ]
        with mock.patch.object(
            acknowledge_event.MonitorEventEvidenceCollector,
            "collect_external_review_wait",
            return_value=evidence,
        ):
            wait = acknowledge_event.MonitorEventWaitRecorder(
                self.fixture.handle,
                self.fixture.workflow_id,
                self.fixture.resources,
            ).record()

        saved = self.fixture.store.read().skill_state
        self.assertEqual("unresolved-review-threads", wait["wait_reason"])
        self.assertIn("monitor_event_wait", saved)
        self.assertNotIn("monitor_event_ack", saved)

    def test_local_observation_identity_mismatch_fails_closed(self) -> None:
        """Foreign local observation producer가 external read-back 전에 거부됩니다."""
        event = {
            "monitor_event": "event",
            "event_id": "event-123",
            "reason": "ci-failed",
        }
        self.fixture.stage(event)
        payload = self.fixture.observations.read()
        payload["session_id"] = "other-session"
        self.fixture.observations.write(payload)

        with self.assertRaisesRegex(
            acknowledge_event.MonitorAcknowledgementError,
            "session_id identity mismatch",
        ):
            self.fixture.acknowledger().acknowledge()

    def test_expected_route_binds_all_runtime_resource_identities(self) -> None:
        """Expected route를 구성하는 다섯 identity가 하나라도 다르면 거부합니다."""
        event = {
            "monitor_event": "event",
            "event_id": "event-123",
            "reason": "ci-failed",
        }
        self.fixture.stage(event)
        baseline = self.fixture.route()
        mismatches: tuple[tuple[str, object], ...] = (
            ("session_id", "other-session"),
            ("workflow_id", "other-workflow"),
            ("runtime_id", "other-runtime"),
            ("worktree_id", "other-worktree"),
            (
                "observation_resource",
                {"kind": "monitor-observation-cache", "worktree_id": "other-worktree"},
            ),
        )

        for field, invalid_value in mismatches:
            with self.subTest(field=field):
                self.fixture.set_route({**baseline, field: invalid_value})
                with self.assertRaisesRegex(
                    acknowledge_event.MonitorAcknowledgementError,
                    field,
                ):
                    self.fixture.acknowledger().acknowledge()
                self.fixture.set_route(baseline)

    def test_missing_expected_route_fails_before_external_readback(self) -> None:
        """Canonical subscription이 없으면 GitHub collector를 호출하지 않습니다."""
        event = {
            "monitor_event": "event",
            "event_id": "event-123",
            "reason": "ci-failed",
        }
        self.fixture.stage(event)
        self.fixture.set_route(None)

        with (
            mock.patch.object(
                acknowledge_event.MonitorEventEvidenceCollector,
                "collect",
            ) as collect,
            self.assertRaisesRegex(
                acknowledge_event.MonitorAcknowledgementError,
                "monitor_event_subscription",
            ),
        ):
            self.fixture.acknowledger().acknowledge()

        collect.assert_not_called()

    def test_cli_returns_typed_nonzero_for_optimistic_conflict(self) -> None:
        """Optimistic conflict가 stale output 없이 public exit code 2를 반환합니다."""
        error_output = StringIO()
        with (
            mock.patch.object(
                acknowledge_event.MonitorRuntimeResources,
                "resolve",
                return_value=self.fixture.resources,
            ),
            mock.patch.object(
                acknowledge_event.SessionLocator,
                "from_worktree",
                return_value=self.fixture.locator,
            ),
            mock.patch.object(
                acknowledge_event.RuntimeEnvironmentResolver,
                "resolve",
                return_value=self.fixture.binding,
            ),
            mock.patch.object(
                acknowledge_event.StateHandle,
                "attach",
                return_value=self.fixture.handle,
            ),
            mock.patch.object(
                acknowledge_event.MonitorEventAcknowledger,
                "acknowledge",
                side_effect=acknowledge_event.MonitorAcknowledgementConflict(
                    "workflow changed during live ACK read-back; rerun the command"
                ),
            ),
            redirect_stderr(error_output),
        ):
            exit_code = acknowledge_event.main([
                "--workflow-id",
                str(self.fixture.workflow_id),
                "--event-id",
                "event-123",
            ])

        self.assertEqual(2, exit_code)
        self.assertIn("rerun the command", error_output.getvalue())

    def test_public_cli_has_no_process_or_monitor_state_path_selector(self) -> None:
        """Public parser와 implementation에서 caller-selected state path를 차단합니다."""
        source = SCRIPT.read_text(encoding="utf-8")

        self.assertIn('parser.add_argument("--workflow-id", required=True)', source)
        self.assertNotIn('parser.add_argument("--process-state"', source)
        self.assertNotIn('parser.add_argument("--monitor-state"', source)
        self.assertNotIn("process_state_path", source)
        self.assertIn(
            "from monitor_observation_store import MonitorObservationStore",
            source,
        )
        self.assertIn(
            "from monitor_runtime_resources import MonitorRuntimeResources",
            source,
        )
        self.assertNotIn("def _read_local_observation", source)
        self.assertNotIn("def _update_local_ack", source)
        self.assertNotIn("NamedTemporaryFile", source)
        self.assertNotIn("import fcntl", source)
        self.assertNotIn("self._observations.write(", source)


class MonitorEventEvidenceCollectorTest(TestCase):
    """Reason별 live GitHub evidence 의미를 보존합니다."""

    def setUp(self) -> None:
        """Repository root를 command cwd로 사용하는 collector를 제공합니다."""
        self.collector = acknowledge_event.MonitorEventEvidenceCollector(ROOT)

    def test_check_counts_keep_latest_named_check_and_ignore_review_helpers(self) -> None:
        """동일 check 최신값과 review helper 비차단 규칙을 검증합니다."""
        checks: list[object] = [
            {
                "name": "build",
                "status": "COMPLETED",
                "conclusion": "FAILURE",
                "startedAt": "2026-01-01T00:00:00Z",
            },
            {
                "name": "build",
                "status": "COMPLETED",
                "conclusion": "SUCCESS",
                "startedAt": "2026-01-02T00:00:00Z",
            },
            {
                "name": "review",
                "workflowName": "AI Review Auto Approve",
                "status": "COMPLETED",
                "conclusion": "FAILURE",
            },
            {"context": "pending", "state": "PENDING"},
        ]

        self.assertEqual((0, 1), self.collector._check_counts(checks))

    def test_mergeable_terminal_requires_exact_head_and_settled_checks(self) -> None:
        """Mergeable terminal이 exact head와 settled checks를 요구하는지 검증합니다."""
        event = {
            "reason": "mergeable-clean",
            "snapshot": {"headRefOid": "head-1"},
        }
        payload = {
            "state": "OPEN",
            "mergeStateStatus": "CLEAN",
            "reviewDecision": "APPROVED",
            "headRefOid": "head-1",
            "statusCheckRollup": [],
        }
        with (
            mock.patch.object(
                self.collector,
                "_collect_comment_readback",
                return_value=[
                    "collect_comments:TOTAL=0",
                    "collect_comments:UNRESOLVED_THREADS_COUNT=0",
                ],
            ),
            mock.patch.object(self.collector, "_gh_pr_view", return_value=payload),
        ):
            evidence = self.collector._collect_mergeable_terminal_readback(
                "E5presso/neurath",
                42,
                event,
            )

        self.assertIn("terminal_readback:mergeState=CLEAN", evidence)
        self.assertIn("terminal_readback:headRefOid=head-1", evidence)

    def test_ci_evidence_rejects_failed_checks(self) -> None:
        """Live status rollup에 실패 check가 남으면 ACK evidence를 거부합니다."""
        payload = {
            "statusCheckRollup": [
                {
                    "name": "build",
                    "status": "COMPLETED",
                    "conclusion": "FAILURE",
                }
            ]
        }
        with (
            mock.patch.object(self.collector, "_gh_pr_view", return_value=payload),
            self.assertRaisesRegex(ValueError, "still has 1 failed"),
        ):
            self.collector._collect_ci_readback("E5presso/neurath", 42)

    def test_merge_evidence_requires_non_dirty_live_state(self) -> None:
        """Merge-dirty event는 live state가 계속 DIRTY이면 처리되지 않습니다."""
        with (
            mock.patch.object(
                self.collector,
                "_gh_pr_view",
                return_value={"mergeStateStatus": "DIRTY"},
            ),
            self.assertRaisesRegex(ValueError, "still DIRTY"),
        ):
            self.collector._collect_merge_readback("E5presso/neurath", 42)

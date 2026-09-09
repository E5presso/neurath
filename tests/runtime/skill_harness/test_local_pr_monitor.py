"""Local PR monitor의 workflow-local optimistic mailbox 회귀 테스트입니다."""

import importlib.util
import json
import subprocess
import sys
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Protocol, cast
from unittest import TestCase
from unittest.mock import patch

from scripts.agent_harness.session_kernel import (
    ActorId,
    ActorKind,
    ActorLineageAssurance,
    ActorStarted,
    DelegationAssigned,
    DelegationId,
    DelegationReported,
    DelegationResult,
    DelegationTopologyPolicy,
    SessionLocator,
    WorkflowId,
    WorkflowStarted,
)
from scripts.agent_harness.skill_state_store import SkillStateStore
from scripts.agent_harness.state_handle import (
    RuntimeEnvironmentResolver,
    StateHandle,
)
from scripts.agent_harness.worktree_registry import WorktreeIdentityResolver

ROOT = Path(__file__).resolve().parents[3]
MONITOR_PATH = ROOT / ".agents/skills/monitor-pr/scripts/local_pr_monitor.py"
sys.path.insert(0, str(MONITOR_PATH.parent))
SPEC = importlib.util.spec_from_file_location("local_pr_monitor", MONITOR_PATH)
assert SPEC is not None
local_pr_monitor = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules["local_pr_monitor"] = local_pr_monitor
SPEC.loader.exec_module(local_pr_monitor)


class ResumeAdapterView(Protocol):
    """Tests가 patch하는 resume adapter의 structural contract입니다."""

    def resume(self, event: dict[str, object]) -> dict[str, object]:
        """Claimed event를 runtime turn으로 전달합니다."""

    def inspect_turn(self, turn_id: str) -> dict[str, object]:
        """Exact runtime turn을 조회합니다."""


class LocalPrMonitorView(Protocol):
    """Dynamic module에서 load한 monitor의 test-facing contract입니다."""

    _resume_adapter: ResumeAdapterView

    def run_once(self, snapshot: dict[str, object]) -> object:
        """GitHub snapshot 한 건을 처리합니다."""

    def _claimant_process_is_live(self, active_claim: dict[str, object]) -> bool:
        """Persisted claim의 exact runtime process 생존 여부를 반환합니다."""


class MonitorFixture:
    """Temporary Git worktree와 exact session workflow를 함께 준비합니다."""

    def __init__(self, lifecycle: str = "active") -> None:
        """Owner lifecycle과 빈 mailbox를 가진 fixture를 생성합니다."""
        self._temporary = TemporaryDirectory()
        self.worktree = Path(self._temporary.name)
        subprocess.run(("git", "init", "-q", str(self.worktree)), check=True)
        self.environment: dict[str, object] = {"CODEX_THREAD_ID": "owner-thread"}
        self.locator = SessionLocator.from_worktree(self.worktree)
        self.binding = RuntimeEnvironmentResolver().resolve(self.environment)
        self.handle = StateHandle.initialize(self.locator, self.binding)
        self.workflow_id = WorkflowId("process-ticket-131")
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
                            "state": lifecycle,
                            "owner_session_id": str(self.handle.session_id),
                            "source": "native-hook",
                            "transitioned_at_epoch": 100.0,
                            "activity": "fixture",
                        },
                        "monitor_mailbox": {
                            "pending_events": [],
                            "seen_event_ids": [],
                            "active_claim": None,
                        },
                        "monitor_event_ack": None,
                    }
                },
                idempotency_key="fixture:workflow",
            )
        )
        self.identity = WorktreeIdentityResolver().resolve(self.worktree)

    def close(self) -> None:
        """Temporary fixture를 정리합니다."""
        self._temporary.cleanup()

    def monitor(
        self,
        *,
        resume_command: str | None = "/usr/bin/true",
        runtime_id: str = "runtime-a",
    ) -> LocalPrMonitorView:
        """Path selector 없이 runtime-bound monitor를 반환합니다."""
        return cast(
            LocalPrMonitorView,
            local_pr_monitor.LocalPrMonitor(
                handle=self.handle,
                workflow_id=self.workflow_id,
                worktree=self.identity,
                runtime_id=runtime_id,
                repo="E5presso/neurath",
                pr_number=131,
                poll_interval_seconds=30,
                resume_command=resume_command,
            ),
        )

    def skill_state(self) -> dict[str, object]:
        """Exact workflow의 current skill state를 반환합니다."""
        return dict(SkillStateStore(self.handle, self.workflow_id).read().skill_state)

    def mailbox(self) -> dict[str, object]:
        """Current workflow mailbox를 object로 반환합니다."""
        mailbox = self.skill_state().get("monitor_mailbox")
        if not isinstance(mailbox, Mapping):
            raise TypeError("fixture monitor mailbox must be an object")
        return dict(mailbox)

    def lifecycle(self) -> dict[str, object]:
        """Current workflow owner lifecycle을 object로 반환합니다."""
        lifecycle = self.skill_state().get("owner_lifecycle")
        if not isinstance(lifecycle, Mapping):
            raise TypeError("fixture owner lifecycle must be an object")
        return dict(lifecycle)

    def pending_events(self) -> list[dict[str, object]]:
        """Current mailbox의 validated pending event 배열을 반환합니다."""
        pending = self.mailbox().get("pending_events")
        if not isinstance(pending, list) or any(not isinstance(row, Mapping) for row in pending):
            raise TypeError("fixture pending events must be an object array")
        return [dict(row) for row in pending]

    def seen_event_ids(self) -> list[str]:
        """Current mailbox의 validated event identity 배열을 반환합니다."""
        seen = self.mailbox().get("seen_event_ids")
        if not isinstance(seen, list) or any(not isinstance(row, str) for row in seen):
            raise TypeError("fixture seen event identities must be a string array")
        return list(seen)

    def active_claim(self) -> dict[str, object] | None:
        """Current mailbox의 optional active claim을 반환합니다."""
        claim = self.mailbox().get("active_claim")
        if claim is None:
            return None
        if not isinstance(claim, Mapping):
            raise TypeError("fixture active claim must be an object or null")
        return dict(claim)

    def update(self, values: Mapping[str, object]) -> None:
        """Test prerequisite를 optimistic workflow transaction으로 적용합니다."""
        SkillStateStore(self.handle, self.workflow_id).update(values)

    def add_reported_delegation(
        self,
        *,
        delegation_id: str,
        workflow_id: str,
        suffix: str,
    ) -> None:
        """Exact 또는 foreign workflow에 귀속된 reported child result를 추가합니다."""
        child_id = ActorId(f"codex:child-{suffix}")
        self.handle.apply(
            ActorStarted(
                session_id=self.handle.session_id,
                actor_id=child_id,
                parent_actor_id=self.handle.actor_id,
                kind=ActorKind.SUBAGENT,
                idempotency_key=f"fixture:child:{suffix}",
                lineage_assurance=ActorLineageAssurance.HOST_ATTESTED,
            )
        )
        assignment = json.dumps(
            {
                "kind": "review-code",
                "scope": f"scope-{suffix}",
                "started_at": "2026-08-04T00:00:00+00:00",
                "target": f"child-{suffix}",
                "workflow_id": workflow_id,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        typed_delegation_id = DelegationId(delegation_id)
        self.handle.apply(
            DelegationAssigned(
                session_id=self.handle.session_id,
                delegation_id=typed_delegation_id,
                owner_actor_id=self.handle.actor_id,
                target_actor_id=child_id,
                assignment=assignment,
                idempotency_key=f"fixture:assignment:{suffix}",
                topology_policy=DelegationTopologyPolicy.DIRECT_CHILD,
            )
        )
        child_environment = {
            "CODEX_THREAD_ID": str(self.handle.session_id),
            "NEURATH_AGENT_SESSION_ID": str(self.handle.session_id),
            "NEURATH_AGENT_ACTOR_ID": str(child_id),
            "NEURATH_AGENT_RUNTIME": "codex",
        }
        child_handle = StateHandle.attach(
            self.locator,
            RuntimeEnvironmentResolver().resolve(child_environment),
        )
        child_handle.apply(
            DelegationReported(
                session_id=self.handle.session_id,
                delegation_id=typed_delegation_id,
                reporter_actor_id=child_id,
                result=DelegationResult(
                    verdict="pass",
                    summary=f"summary-{suffix}",
                    outcome_ref=f"artifact://{suffix}",
                    blocking_findings=(),
                ),
                idempotency_key=f"fixture:report:{suffix}",
            )
        )


class LocalPrMonitorTest(TestCase):
    """실제 GitHub delta만 exact workflow owner turn으로 전달되는지 검증합니다."""

    def test_check_summary_counts_terminal_negative_conclusions(self) -> None:
        """GitHub terminal-negative check는 모두 CI failure입니다."""
        for conclusion in (
            "ACTION_REQUIRED",
            "TIMED_OUT",
            "CANCELLED",
            "FAILURE",
            "STARTUP_FAILURE",
            "STALE",
        ):
            with self.subTest(conclusion=conclusion):
                summary = local_pr_monitor.CheckSummary([
                    {
                        "name": "required-ci",
                        "status": "COMPLETED",
                        "conclusion": conclusion,
                        "startedAt": "2026-07-12T00:00:00Z",
                    }
                ])
                self.assertEqual(1, summary.failed_count)
                self.assertEqual(0, summary.pending_count)

    def test_classifier_emits_ci_failure_only_for_changed_actionable_check(self) -> None:
        """ACK한 동일 failure는 조용하고 새 check identity만 새 delta입니다."""
        classifier = local_pr_monitor.EventClassifier()
        first = self._snapshot(checks=[self._check("ci-a", "FAILURE")])
        last_seen = classifier.last_seen_from_snapshot(first)

        repeated = classifier.classify(first, last_seen)
        changed = classifier.classify(
            self._snapshot(checks=[self._check("ci-b", "FAILURE")]),
            last_seen,
        )

        self.assertIsNone(repeated)
        self.assertIsNotNone(changed)
        assert changed is not None
        self.assertEqual("ci-failed", changed.reason)
        self.assertIn("actionableChecks", changed.detected_change or {})

    def test_classifier_suppresses_automatic_progress_and_repeated_sticky_state(self) -> None:
        """자동 review 진행과 동일 sticky 상태는 owner wake 신호가 아닙니다."""
        classifier = local_pr_monitor.EventClassifier()
        dirty = self._snapshot(merge_state="DIRTY")
        previous = classifier.last_seen_from_snapshot(
            self._snapshot(head_oid="old", review_decision="APPROVED")
        )
        automatic = classifier.classify(
            self._snapshot(
                head_oid="new",
                reviews=[
                    {
                        "id": 1,
                        "state": "COMMENTED",
                        "body": "AI review 결과: 진행 중",
                        "submitted_at": "2026-07-12T00:01:00Z",
                        "commit_id": "new",
                        "user": {"login": "github-actions[bot]"},
                    }
                ],
            ),
            previous,
        )

        self.assertIsNone(classifier.classify(dirty, classifier.last_seen_from_snapshot(dirty)))
        self.assertIsNone(automatic)

    def test_classifier_wakes_for_human_comment_update_and_thread_identity(self) -> None:
        """사람 comment 수정과 같은 수의 다른 thread는 각각 실제 delta입니다."""
        classifier = local_pr_monitor.EventClassifier()
        prior_comment = self._snapshot(pull_comments=[self._comment(10, "2026-07-12T00:00:00Z")])
        comment_event = classifier.classify(
            self._snapshot(pull_comments=[self._comment(10, "2026-07-12T00:01:00Z")]),
            classifier.last_seen_from_snapshot(prior_comment),
        )
        prior_thread = self._snapshot(review_threads=[self._human_thread("thread-a")])
        thread_event = classifier.classify(
            self._snapshot(review_threads=[self._human_thread("thread-b")]),
            classifier.last_seen_from_snapshot(prior_thread),
        )

        self.assertEqual("comments-changed", comment_event.reason if comment_event else None)
        self.assertEqual(("10",), comment_event.stale_handled_ids if comment_event else ())
        self.assertEqual("review-blocked", thread_event.reason if thread_event else None)

    def test_classifier_emits_mergeable_clean_only_for_approved_snapshot(self) -> None:
        """Clean snapshot은 GitHub approval까지 있어야 terminal이 됩니다."""
        classifier = local_pr_monitor.EventClassifier()
        approved = classifier.classify(
            self._snapshot(
                merge_state="CLEAN",
                review_decision="APPROVED",
                reviews=[
                    {
                        "id": 1,
                        "state": "APPROVED",
                        "body": "자동 승인",
                        "submitted_at": "2026-07-12T00:01:00Z",
                        "commit_id": "abc123",
                        "user": {"login": "github-actions[bot]"},
                    }
                ],
            ),
            {},
        )
        blocked = classifier.classify(
            self._snapshot(merge_state="CLEAN", review_decision="REVIEW_REQUIRED"),
            {},
        )

        self.assertEqual(
            ("terminal", "mergeable-clean"),
            (approved.kind, approved.reason) if approved else None,
        )
        self.assertIsNone(blocked)

    def test_active_owner_stages_event_without_starting_turn(self) -> None:
        """Active owner의 event는 workflow mailbox에만 exact-once 저장됩니다."""
        fixture = MonitorFixture("active")
        try:
            monitor = fixture.monitor()
            snapshot = self._snapshot(pull_comments=[self._comment(1)])
            with patch.object(monitor._resume_adapter, "resume") as resume:
                monitor.run_once(snapshot)
                monitor.run_once(snapshot)
            pending_count = len(fixture.pending_events())
            seen_count = len(fixture.seen_event_ids())
        finally:
            fixture.close()

        resume.assert_not_called()
        self.assertEqual(1, pending_count)
        self.assertEqual(1, seen_count)

    def test_idle_owner_claims_and_binds_exactly_one_turn(self) -> None:
        """Idle owner만 pending event를 claim하고 exact app-server turn에 결속합니다."""
        fixture = MonitorFixture("idle")
        try:
            monitor = fixture.monitor()
            with (
                patch.object(
                    monitor._resume_adapter,
                    "resume",
                    return_value=self._timed_out_delivery("turn-1"),
                ) as resume,
                redirect_stdout(StringIO()),
            ):
                monitor.run_once(self._snapshot(pull_comments=[self._comment(2)]))
            claim = fixture.active_claim()
            lifecycle = fixture.lifecycle()
        finally:
            fixture.close()

        resume.assert_called_once()
        self.assertEqual("turn-1", claim.get("turn_id") if claim else None)
        self.assertEqual("monitor-delivery", lifecycle["source"])

    def test_competing_monitors_retry_conflict_and_start_one_turn(self) -> None:
        """동시 CAS 충돌 뒤에도 하나의 monitor만 owner turn을 시작합니다."""
        fixture = MonitorFixture("idle")
        try:
            first = fixture.monitor(runtime_id="runtime-a")
            second = fixture.monitor(runtime_id="runtime-b")
            snapshot = self._snapshot(pull_comments=[self._comment(3)])
            with (
                patch.object(
                    local_pr_monitor.ResumeAdapter,
                    "resume",
                    return_value=self._timed_out_delivery("turn-atomic"),
                ) as resume,
                redirect_stdout(StringIO()),
                ThreadPoolExecutor(max_workers=2) as executor,
            ):
                list(executor.map(lambda monitor: monitor.run_once(snapshot), (first, second)))
            claim = fixture.active_claim()
        finally:
            fixture.close()

        self.assertEqual(1, resume.call_count)
        self.assertEqual("turn-atomic", claim.get("turn_id") if claim else None)

    def test_deferred_delivery_returns_event_to_fifo_without_phantom_turn(self) -> None:
        """Active-thread defer는 foreign turn을 bind하지 않고 claim을 FIFO로 되돌립니다."""
        fixture = MonitorFixture("idle")
        try:
            monitor = fixture.monitor()
            deferred = {
                "resume_status": "pending-delivery",
                "delivery_method": "active-turn-deferred",
                "turn_completion": {"status": "deferred", "turnId": "foreign-turn"},
            }
            with (
                patch.object(monitor._resume_adapter, "resume", return_value=deferred),
                redirect_stdout(StringIO()),
            ):
                monitor.run_once(self._snapshot(pull_comments=[self._comment(4)]))
            claim = fixture.active_claim()
            pending_count = len(fixture.pending_events())
            lifecycle = fixture.lifecycle()
        finally:
            fixture.close()

        self.assertIsNone(claim)
        self.assertEqual(1, pending_count)
        self.assertEqual("idle", lifecycle["state"])

    def test_bound_timeout_is_inspected_without_duplicate_prompt(self) -> None:
        """Delivery timeout은 exact claim을 유지하고 같은 prompt를 재전달하지 않습니다."""
        fixture = MonitorFixture("idle")
        try:
            monitor = fixture.monitor()
            snapshot = self._snapshot(pull_comments=[self._comment(5)])
            with (
                patch.object(
                    monitor._resume_adapter,
                    "resume",
                    return_value=self._timed_out_delivery("turn-5"),
                ) as resume,
                patch.object(
                    monitor._resume_adapter,
                    "inspect_turn",
                    return_value={"turn": {"id": "turn-5", "status": "inProgress"}},
                ) as inspect,
                redirect_stdout(StringIO()),
            ):
                monitor.run_once(snapshot)
                monitor.run_once(snapshot)
            claim = fixture.active_claim()
        finally:
            fixture.close()

        resume.assert_called_once()
        inspect.assert_called_once_with("turn-5")
        self.assertEqual("turn-5", claim.get("turn_id") if claim else None)

    def test_terminal_delivery_requires_ack_except_external_terminal(self) -> None:
        """일반 work event는 ACK 전 recovering이고 merged는 자체 소비 가능합니다."""
        fixture = MonitorFixture("idle")
        try:
            monitor = fixture.monitor()
            snapshot = self._snapshot(pull_comments=[self._comment(6)])
            with (
                patch.object(
                    monitor._resume_adapter,
                    "resume",
                    return_value=self._completed_delivery("turn-work"),
                ),
                redirect_stdout(StringIO()),
            ):
                monitor.run_once(snapshot)
            self.assertEqual("recovering", fixture.lifecycle()["state"])
            fixture.update({
                "owner_lifecycle": {
                    "state": "idle",
                    "owner_session_id": "owner-thread",
                    "source": "fixture",
                    "transitioned_at_epoch": 200.0,
                },
                "monitor_mailbox": {
                    "pending_events": [],
                    "seen_event_ids": fixture.seen_event_ids(),
                    "active_claim": None,
                },
            })
            with (
                patch.object(
                    monitor._resume_adapter,
                    "resume",
                    return_value=self._completed_delivery("turn-merged"),
                ),
                redirect_stdout(StringIO()),
            ):
                monitor.run_once(self._snapshot(pr_state="MERGED"))
            merged_mailbox = fixture.mailbox()
        finally:
            fixture.close()

        self.assertIsNone(merged_mailbox["active_claim"])

    def test_reported_delegation_matches_owner_and_workflow_exactly(self) -> None:
        """다른 workflow child result는 현재 monitor mailbox에 들어오지 않습니다."""
        fixture = MonitorFixture("active")
        try:
            fixture.add_reported_delegation(
                delegation_id="delegation-matching",
                workflow_id=str(fixture.workflow_id),
                suffix="matching",
            )
            fixture.add_reported_delegation(
                delegation_id="delegation-foreign",
                workflow_id="different-workflow",
                suffix="foreign",
            )
            monitor = fixture.monitor()
            monitor.run_once(self._snapshot())
            pending = fixture.pending_events()
        finally:
            fixture.close()

        delegate_events = [
            event
            for event in pending
            if isinstance(event, Mapping) and event.get("reason") == "delegate-result-ready"
        ]
        self.assertEqual(1, len(delegate_events))
        fingerprint = delegate_events[0].get("fingerprint")
        self.assertIsInstance(fingerprint, Mapping)
        assert isinstance(fingerprint, Mapping)
        result = fingerprint.get("delegate_result")
        self.assertIsInstance(result, Mapping)
        assert isinstance(result, Mapping)
        self.assertEqual(
            "delegation-matching",
            result["delegation_id"],
        )

    def test_monitor_receipt_has_session_and_workflow_without_process_state_path(self) -> None:
        """Local observation receipt는 canonical identity를 담고 legacy path를 담지 않습니다."""
        fixture = MonitorFixture("active")
        try:
            monitor = fixture.monitor()
            observation_path = fixture.worktree / ".monitor-pr/monitor-state.json"
            observations = local_pr_monitor.MonitorObservationStore(observation_path)
            observations.write({
                    "process_state_path": "/obsolete/worktree/.process-state.json",
                    "unknown_legacy_field": "must-not-survive",
                    "last_observed": {"pr_state": "OPEN"},
                })
            monitor.run_once(self._snapshot())
            state = observations.read_required()
            legacy_path_exists = observation_path.exists()
        finally:
            fixture.close()

        self.assertEqual("owner-thread", state["session_id"])
        self.assertEqual("process-ticket-131", state["workflow_id"])
        self.assertNotIn("process_state_path", state)
        self.assertNotIn("unknown_legacy_field", state)
        self.assertFalse(legacy_path_exists)

    def test_observation_cache_has_a_local_only_store_boundary(self) -> None:
        """Local observation JSON은 legacy canonical-style state helper를 재사용하지 않습니다."""
        source = MONITOR_PATH.read_text(encoding="utf-8")

        self.assertIn("from monitor_observation_store import MonitorObservationStore", source)
        self.assertNotIn("from monitor_state_store import", source)
        self.assertNotIn('with_name("monitor_state_store.py")', source)

    def test_claimant_liveness_matches_runtime_workflow_and_process_command(self) -> None:
        """PID 재사용은 exact runtime/workflow command가 아니면 live claim으로 보지 않습니다."""
        fixture = MonitorFixture("idle")
        try:
            monitor = fixture.monitor(runtime_id="runtime-exact")
            claim: dict[str, object] = {
                "claimant_pid": 123,
                "claimant_runtime_id": "runtime-exact",
                "session_id": str(fixture.handle.session_id),
                "workflow_id": str(fixture.workflow_id),
            }
            exact = (
                "python local_pr_monitor.py --repo E5presso/neurath --pr-number 131 "
                "--workflow-id process-ticket-131 --runtime-id runtime-exact"
            )
            foreign = exact.replace("runtime-exact", "runtime-foreign")
            with patch.object(
                local_pr_monitor.subprocess,
                "run",
                return_value=subprocess.CompletedProcess([], 0, exact, ""),
            ):
                self.assertTrue(monitor._claimant_process_is_live(claim))
            with patch.object(
                local_pr_monitor.subprocess,
                "run",
                return_value=subprocess.CompletedProcess([], 0, foreign, ""),
            ):
                self.assertFalse(monitor._claimant_process_is_live(claim))
        finally:
            fixture.close()

    def test_event_identity_ignores_delivery_route(self) -> None:
        """Session/workflow route 변화는 GitHub occurrence identity를 바꾸지 않습니다."""
        payload = {
            "monitor_event": "event",
            "reason": "comments-changed",
            "snapshot": {"headRefOid": "abc123"},
            "observation": {"headRefOid": "abc123"},
            "repo": "E5presso/neurath",
            "pr_number": 131,
        }
        first = local_pr_monitor.MonitorEventIdentity.create({
            **payload,
            "session_id": "session-a",
            "workflow_id": "workflow-a",
        })
        second = local_pr_monitor.MonitorEventIdentity.create({
            **payload,
            "session_id": "session-b",
            "workflow_id": "workflow-b",
        })
        self.assertEqual(first, second)

    def test_application_requires_workflow_and_rejects_legacy_path_selectors(self) -> None:
        """Public CLI는 workflow selector만 받고 state/worktree/thread selector를 거부합니다."""
        parser = local_pr_monitor.LocalPrMonitorApplication().parser()
        with redirect_stderr(StringIO()):
            with self.assertRaises(SystemExit):
                parser.parse_args(("--repo", "E5presso/neurath", "--pr-number", "131"))
            with self.assertRaises(SystemExit):
                parser.parse_args((
                    "--repo",
                    "E5presso/neurath",
                    "--pr-number",
                    "131",
                    "--workflow-id",
                    "workflow-a",
                    "--runtime-id",
                    "runtime-a",
                    "--process-state-path",
                    "/tmp/legacy.json",
                ))

    def _snapshot(
        self,
        *,
        merge_state: str = "BLOCKED",
        review_decision: str = "REVIEW_REQUIRED",
        head_oid: str = "abc123",
        checks: list[dict[str, object]] | None = None,
        pull_comments: list[dict[str, object]] | None = None,
        issue_comments: list[dict[str, object]] | None = None,
        reviews: list[dict[str, object]] | None = None,
        review_threads: list[dict[str, object]] | None = None,
        pr_state: str = "OPEN",
    ) -> dict[str, object]:
        return {
            "pr": {
                "mergeStateStatus": merge_state,
                "reviewDecision": review_decision,
                "state": pr_state,
                "headRefOid": head_oid,
                "labels": [],
                "statusCheckRollup": checks or [],
            },
            "pull_comments": pull_comments or [],
            "issue_comments": issue_comments or [],
            "reviews": reviews or [],
            "review_threads": review_threads or [],
            "head_commit_date": "2026-07-12T00:00:00Z",
        }

    def _check(self, name: str, conclusion: str) -> dict[str, object]:
        return {
            "name": name,
            "status": "COMPLETED",
            "conclusion": conclusion,
            "startedAt": "2026-07-12T00:00:00Z",
        }

    def _comment(
        self,
        comment_id: int,
        updated_at: str = "2026-07-12T00:00:00Z",
    ) -> dict[str, object]:
        return {
            "id": comment_id,
            "body": "수정이 필요합니다",
            "created_at": updated_at,
            "updated_at": updated_at,
            "user": {"login": "human-reviewer"},
        }

    def _human_thread(self, thread_id: str) -> dict[str, object]:
        return {
            "id": thread_id,
            "isResolved": False,
            "comments": {
                "nodes": [
                    {
                        "id": f"comment-{thread_id}",
                        "body": "수정이 필요합니다",
                        "author": {"login": "human-reviewer"},
                        "pullRequestReview": {"state": "SUBMITTED"},
                    }
                ]
            },
        }

    def _timed_out_delivery(self, turn_id: str) -> dict[str, object]:
        return {
            "resume_status": "invoked",
            "delivery_method": "turn/start",
            "response": {"turn": {"id": turn_id, "status": "inProgress"}},
            "turn_completion": {
                "status": "timeout",
                "turnId": turn_id,
                "timeout_seconds": 5,
            },
        }

    def _completed_delivery(self, turn_id: str) -> dict[str, object]:
        return {
            "resume_status": "invoked",
            "delivery_method": "turn/start",
            "response": {"turn": {"id": turn_id, "status": "completed"}},
            "turn_completion": {
                "status": "completed",
                "turnId": turn_id,
                "turn": {"id": turn_id, "status": "completed"},
            },
        }

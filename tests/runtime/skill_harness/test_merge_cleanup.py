"""Merged ticket worktree cleanup의 root checkout invariant를 검증합니다."""

import hashlib
import importlib.util
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Self
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
)
from scripts.agent_harness.skill_state_store import SkillStateConflict
from scripts.agent_harness.worktree_registry import (
    CanonicalWorktreeIdentity,
    WorktreeClaim,
    WorktreeClaimStatus,
    WorktreeIdentityResolver,
    WorktreeLeaseConflict,
    WorktreeNotClaimed,
    WorktreeRegistry,
)

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / ".agents/skills/process-ticket/scripts/merge_cleanup.py"
SPEC = importlib.util.spec_from_file_location("process_ticket_merge_cleanup", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MERGE_CLEANUP = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MERGE_CLEANUP
SPEC.loader.exec_module(MERGE_CLEANUP)


class MergeCleanupTest(TestCase):
    """Root checkout과 ticket worktree를 함께 정리하는 atomic boundary를 검증합니다."""

    def test_cleanup_fast_forwards_real_root_checkout_before_removing_worktree(self) -> None:
        """성공 시 root HEAD, index, worktree가 remote trunk과 정확히 일치합니다."""
        with MergeCleanupFixture() as fixture:
            fixture.publish_trunk_commit()
            identity, claim, registry = fixture.claim_worktree()
            ticket_head_oid = fixture.git("rev-parse", "task/128")

            receipt = MERGE_CLEANUP.MergedWorktreeCleanup(
                identity,
                claim,
                registry,
            ).complete()

            self.assertEqual(fixture.git("rev-parse", "origin/trunk"), receipt["root_head"])
            self.assertEqual(fixture.git("rev-parse", "HEAD"), receipt["root_head"])
            self.assertEqual(ticket_head_oid, receipt["ticket_head_oid"])
            self.assertEqual(
                64,
                len(str(receipt["cleanup_reservation_fencing_token_sha256"])),
            )
            self.assertEqual("", fixture.git("status", "--porcelain=v1", "--untracked-files=all"))
            self.assertTrue((fixture.repo / "published.txt").is_file())
            self.assertFalse(fixture.worktree.exists())
            self.assertNotIn("task/128", fixture.git("branch", "--list", "task/128"))
            self.assertTrue(fixture.cleanup_receipt.is_file())
            self.assertTrue(receipt["worktree_claim_released"])
            with self.assertRaises(WorktreeNotClaimed):
                registry.get(identity.worktree_id)

    def test_bare_root_is_rejected_before_ticket_worktree_removal(self) -> None:
        """Root가 bare이면 어떤 cleanup mutation도 시작하지 않습니다."""
        with MergeCleanupFixture() as fixture:
            identity, claim, registry = fixture.claim_worktree()
            fixture.git_with_dir("config", "core.bare", "true")

            with self.assertRaisesRegex(
                MERGE_CLEANUP.MergeCleanupError,
                "root repository must be non-bare",
            ):
                MERGE_CLEANUP.MergedWorktreeCleanup(
                    identity,
                    claim,
                    registry,
                ).complete()

            self.assertTrue(fixture.worktree.is_dir())
            self.assertIn("task/128", fixture.git_with_dir("branch", "--list", "task/128"))
            self.assertFalse(fixture.cleanup_receipt.exists())

    def test_ref_only_sync_is_rejected_as_dirty_root_checkout(self) -> None:
        """Develop ref만 전진하고 index/worktree가 과거 tree이면 cleanup을 거부합니다."""
        with MergeCleanupFixture() as fixture:
            identity, claim, registry = fixture.claim_worktree()
            fixture.publish_trunk_commit()
            fixture.git("fetch", "origin")
            fixture.git_with_dir(
                "update-ref",
                "refs/heads/trunk",
                fixture.git("rev-parse", "origin/trunk"),
            )

            with self.assertRaisesRegex(
                MERGE_CLEANUP.MergeCleanupError,
                "root checkout must be clean",
            ):
                MERGE_CLEANUP.MergedWorktreeCleanup(
                    identity,
                    claim,
                    registry,
                ).complete()

            self.assertTrue(fixture.worktree.is_dir())
            self.assertFalse(fixture.cleanup_receipt.exists())

    def test_handoff_before_cleanup_is_fenced_before_ticket_removal(self) -> None:
        """Stale cleanup은 새 owner의 worktree나 branch를 삭제하기 전에 충돌합니다."""
        with MergeCleanupFixture() as fixture:
            identity, stale_claim, registry = fixture.claim_worktree()
            locator = SessionLocator.from_worktree(fixture.worktree)
            SessionKernel(locator).apply(
                SessionStarted(
                    session_id=SessionId("next-thread"),
                    resume_id=ResumeId("next-thread"),
                    runtime=SessionRuntime.CODEX,
                    root_actor_id=ActorId("codex:session:next-thread"),
                    idempotency_key="fixture:next-session-start",
                )
            )
            current = registry.handoff(
                stale_claim,
                next_session_id=SessionId("next-thread"),
                next_actor_id=ActorId("codex:session:next-thread"),
            )

            with self.assertRaises(WorktreeLeaseConflict):
                MERGE_CLEANUP.MergedWorktreeCleanup(
                    identity,
                    stale_claim,
                    registry,
                ).complete()

            self.assertTrue(fixture.worktree.is_dir())
            self.assertIn("task/128", fixture.git("branch", "--list", "task/128"))
            self.assertEqual(
                current.fencing_token,
                registry.get(identity.worktree_id).fencing_token,
            )
            self.assertFalse(fixture.cleanup_receipt.exists())

    def test_stale_cleanup_conflicts_before_any_git_mutation(self) -> None:
        """Stale cleanup은 fetch prune이 shared remote ref를 바꾸기 전에 충돌합니다."""
        with MergeCleanupFixture() as fixture:
            proof_ref = "refs/remotes/origin/cleanup-proof"
            fixture.publish_remote_ref("cleanup-proof")
            proof_head = fixture.git("rev-parse", proof_ref)
            fixture.delete_upstream_ref("cleanup-proof")
            identity, stale_claim, registry = fixture.claim_worktree()
            locator = SessionLocator.from_worktree(fixture.worktree)
            SessionKernel(locator).apply(
                SessionStarted(
                    session_id=SessionId("next-thread"),
                    resume_id=ResumeId("next-thread"),
                    runtime=SessionRuntime.CODEX,
                    root_actor_id=ActorId("codex:session:next-thread"),
                    idempotency_key="fixture:next-session-start",
                )
            )
            registry.handoff(
                stale_claim,
                next_session_id=SessionId("next-thread"),
                next_actor_id=ActorId("codex:session:next-thread"),
            )

            with self.assertRaises(WorktreeLeaseConflict):
                MERGE_CLEANUP.MergedWorktreeCleanup(
                    identity,
                    stale_claim,
                    registry,
                ).complete()

            self.assertEqual(proof_head, fixture.git("rev-parse", proof_ref))

    def test_git_failure_keeps_exact_reservation_for_safe_retry(self) -> None:
        """Reservation 뒤 Git 실패는 fail-closed 상태를 남겨 exact retry를 허용합니다."""
        with MergeCleanupFixture() as fixture:
            identity, claim, registry = fixture.claim_worktree()
            cleanup = MERGE_CLEANUP.MergedWorktreeCleanup(
                identity,
                claim,
                registry,
                remote_ref="origin/recovered",
            )

            with self.assertRaises(subprocess.CalledProcessError):
                cleanup.complete()

            reservation = registry.get(identity.worktree_id)
            self.assertEqual(WorktreeClaimStatus.CLEANUP_RESERVED, reservation.status)
            fixture.create_upstream_ref("recovered")

            receipt = MERGE_CLEANUP.MergedWorktreeCleanup(
                identity,
                reservation,
                registry,
                remote_ref="origin/recovered",
            ).complete()

            self.assertTrue(receipt["worktree_claim_released"])
            with self.assertRaises(WorktreeNotClaimed):
                registry.get(identity.worktree_id)

    def test_new_invocation_resumes_after_worktree_removal_before_claim_completion(
        self,
    ) -> None:
        """새 process는 삭제된 cwd 없이 exact cleanup reservation을 끝냅니다."""
        with MergeCleanupFixture() as fixture:
            identity, _claim, registry = fixture.claim_worktree()
            environment = {"CODEX_THREAD_ID": "owner-thread"}
            workflow_id = WorkflowId("process-ticket-128")

            with (
                mock.patch.object(
                    MERGE_CLEANUP.WorktreeRegistry,
                    "complete_cleanup",
                    side_effect=SimulatedProcessCrash,
                ),
                self.assertRaises(SimulatedProcessCrash),
            ):
                MERGE_CLEANUP.MergeCleanupApplication().run(
                    environment=environment,
                    cwd=fixture.worktree,
                    workflow_id=workflow_id,
                    base_branch="trunk",
                    remote_ref="origin/trunk",
                )

            reservation = registry.get(identity.worktree_id)
            self.assertEqual(WorktreeClaimStatus.CLEANUP_RESERVED, reservation.status)
            self.assertFalse(fixture.worktree.exists())
            self.assertNotIn("task/128", fixture.git("branch", "--list", "task/128"))
            self.assertFalse(fixture.cleanup_receipt.exists())
            self.assertIsNotNone(fixture.cleanup_intent(workflow_id))

            receipt = MERGE_CLEANUP.MergeCleanupApplication().run(
                environment=environment,
                cwd=fixture.repo,
                workflow_id=workflow_id,
                base_branch="trunk",
                remote_ref="origin/trunk",
            )

            self.assertTrue(receipt["worktree_claim_released"])
            self.assertTrue(fixture.cleanup_receipt.is_file())
            self.assertIsNone(fixture.cleanup_intent(workflow_id))

            retried = MERGE_CLEANUP.MergeCleanupApplication().run(
                environment=environment,
                cwd=fixture.repo,
                workflow_id=workflow_id,
                base_branch="trunk",
                remote_ref="origin/trunk",
            )

            self.assertEqual(receipt, retried)
            with self.assertRaises(WorktreeNotClaimed):
                registry.get(identity.worktree_id)

    def test_cleanup_intent_cas_conflict_precedes_every_git_mutation(self) -> None:
        """Intent CAS conflict는 fetch prune을 포함한 Git mutation 전에 반환됩니다."""
        with MergeCleanupFixture() as fixture:
            proof_ref = "refs/remotes/origin/cleanup-intent-proof"
            fixture.publish_remote_ref("cleanup-intent-proof")
            proof_head = fixture.git("rev-parse", proof_ref)
            fixture.delete_upstream_ref("cleanup-intent-proof")
            fixture.claim_worktree()

            with (
                mock.patch.object(
                    MERGE_CLEANUP.SkillStateStore,
                    "compare_and_update",
                    side_effect=SkillStateConflict("simulated workflow conflict"),
                ),
                self.assertRaises(SkillStateConflict),
            ):
                MERGE_CLEANUP.MergeCleanupApplication().run(
                    environment={"CODEX_THREAD_ID": "owner-thread"},
                    cwd=fixture.worktree,
                    workflow_id=WorkflowId("process-ticket-128"),
                    base_branch="trunk",
                    remote_ref="origin/trunk",
                )

            self.assertEqual(proof_head, fixture.git("rev-parse", proof_ref))
            self.assertTrue(fixture.worktree.is_dir())

    def test_new_invocation_rebuilds_receipt_after_claim_release_crash(self) -> None:
        """Claim release 뒤 receipt 전 crash도 workflow intent에서 root 재개됩니다."""
        with MergeCleanupFixture() as fixture:
            identity, _claim, registry = fixture.claim_worktree()
            workflow_id = WorkflowId("process-ticket-128")
            environment = {"CODEX_THREAD_ID": "owner-thread"}

            with (
                mock.patch.object(
                    MERGE_CLEANUP.MergedWorktreeCleanup,
                    "_build_receipt",
                    side_effect=SimulatedProcessCrash,
                ),
                self.assertRaises(SimulatedProcessCrash),
            ):
                MERGE_CLEANUP.MergeCleanupApplication().run(
                    environment=environment,
                    cwd=fixture.worktree,
                    workflow_id=workflow_id,
                    base_branch="trunk",
                    remote_ref="origin/trunk",
                )

            with self.assertRaises(WorktreeNotClaimed):
                registry.get(identity.worktree_id)
            self.assertIsNotNone(fixture.cleanup_intent(workflow_id))
            self.assertFalse(fixture.cleanup_receipt.exists())

            receipt = MERGE_CLEANUP.MergeCleanupApplication().run(
                environment=environment,
                cwd=fixture.repo,
                workflow_id=workflow_id,
                base_branch="trunk",
                remote_ref="origin/trunk",
            )

            self.assertTrue(receipt["worktree_claim_released"])
            self.assertTrue(fixture.cleanup_receipt.is_file())
            self.assertIsNone(fixture.cleanup_intent(workflow_id))

    def test_same_actor_resumes_two_workflow_cleanup_plans_without_scanning(self) -> None:
        """동일 actor의 두 workflow plan은 서로 덮어쓰지 않고 root에서 재개됩니다."""
        with MergeCleanupFixture() as fixture:
            identity_128, _claim_128, registry = fixture.claim_worktree(
                issue_number=128,
                workflow_id=WorkflowId("process-ticket-128"),
            )
            fixture.create_worktree(129)
            identity_129, _claim_129, _same_registry = fixture.claim_worktree(
                issue_number=129,
                workflow_id=WorkflowId("process-ticket-129"),
            )
            environment = {"CODEX_THREAD_ID": "owner-thread"}

            with mock.patch.object(
                MERGE_CLEANUP.WorktreeRegistry,
                "complete_cleanup",
                side_effect=SimulatedProcessCrash,
            ):
                for issue_number in (128, 129):
                    with self.assertRaises(SimulatedProcessCrash):
                        MERGE_CLEANUP.MergeCleanupApplication().run(
                            environment=environment,
                            cwd=fixture.worktree_for(issue_number),
                            workflow_id=WorkflowId(f"process-ticket-{issue_number}"),
                            base_branch="trunk",
                            remote_ref="origin/trunk",
                        )

            for issue_number in (128, 129):
                self.assertIsNotNone(
                    fixture.cleanup_intent(WorkflowId(f"process-ticket-{issue_number}"))
                )

            for issue_number in (128, 129):
                receipt = MERGE_CLEANUP.MergeCleanupApplication().run(
                    environment=environment,
                    cwd=fixture.repo,
                    workflow_id=WorkflowId(f"process-ticket-{issue_number}"),
                    base_branch="trunk",
                    remote_ref="origin/trunk",
                )
                self.assertEqual(str((identity_128 if issue_number == 128 else identity_129).worktree_id), receipt["worktree_id"])

            for issue_number in (128, 129):
                self.assertIsNone(
                    fixture.cleanup_intent(WorkflowId(f"process-ticket-{issue_number}"))
                )
            for identity in (identity_128, identity_129):
                with self.assertRaises(WorktreeNotClaimed):
                    registry.get(identity.worktree_id)

    def test_late_clean_commit_conflicts_then_fresh_command_replans(self) -> None:
        """Intent 뒤 clean commit은 current command를 막고 fresh retry만 replan합니다."""
        with MergeCleanupFixture() as fixture:
            identity, _claim, registry = fixture.claim_worktree()
            workflow_id = WorkflowId("process-ticket-128")
            original_complete = MERGE_CLEANUP.MergedWorktreeCleanup.complete

            def commit_before_reservation(cleanup: object) -> dict[str, object]:
                """Intent CAS 뒤 ticket branch를 clean commit으로 전진시킵니다."""
                fixture.commit_ticket_change(128, "late-clean.txt")
                return original_complete(cleanup)

            with (
                mock.patch.object(
                    MERGE_CLEANUP.MergedWorktreeCleanup,
                    "complete",
                    new=commit_before_reservation,
                ),
                self.assertRaises(MERGE_CLEANUP.MergeCleanupPlanConflict),
            ):
                MERGE_CLEANUP.MergeCleanupApplication().run(
                    environment={"CODEX_THREAD_ID": "owner-thread"},
                    cwd=fixture.worktree,
                    workflow_id=workflow_id,
                    base_branch="trunk",
                    remote_ref="origin/trunk",
                )

            self.assertEqual(
                WorktreeClaimStatus.ACTIVE,
                registry.get(identity.worktree_id).status,
            )

            receipt = MERGE_CLEANUP.MergeCleanupApplication().run(
                environment={"CODEX_THREAD_ID": "owner-thread"},
                cwd=fixture.worktree,
                workflow_id=workflow_id,
                base_branch="trunk",
                remote_ref="origin/trunk",
            )

            self.assertTrue(receipt["worktree_claim_released"])

    def test_dirty_or_untracked_ticket_conflicts_without_reservation(self) -> None:
        """Intent 뒤 dirty change는 수정 가능한 active worktree를 그대로 남깁니다."""
        with MergeCleanupFixture() as fixture:
            identity, _claim, registry = fixture.claim_worktree()
            workflow_id = WorkflowId("process-ticket-128")
            original_complete = MERGE_CLEANUP.MergedWorktreeCleanup.complete

            def dirty_before_reservation(cleanup: object) -> dict[str, object]:
                """Intent CAS 뒤 ticket worktree에 untracked file을 만듭니다."""
                (fixture.worktree / "untracked.txt").write_text("dirty\n", encoding="utf-8")
                return original_complete(cleanup)

            with (
                mock.patch.object(
                    MERGE_CLEANUP.MergedWorktreeCleanup,
                    "complete",
                    new=dirty_before_reservation,
                ),
                self.assertRaises(MERGE_CLEANUP.MergeCleanupPlanConflict),
            ):
                MERGE_CLEANUP.MergeCleanupApplication().run(
                    environment={"CODEX_THREAD_ID": "owner-thread"},
                    cwd=fixture.worktree,
                    workflow_id=workflow_id,
                    base_branch="trunk",
                    remote_ref="origin/trunk",
                )

            self.assertEqual(
                WorktreeClaimStatus.ACTIVE,
                registry.get(identity.worktree_id).status,
            )
            self.assertTrue((fixture.worktree / "untracked.txt").is_file())
            self.assertFalse(fixture.cleanup_receipt.exists())

    def test_foreign_recreated_reservation_with_same_owner_epoch_is_rejected(self) -> None:
        """같은 owner/epoch라도 intent token과 다른 재생성 reservation은 adopt하지 않습니다."""
        with MergeCleanupFixture() as fixture:
            identity, active, registry = fixture.claim_worktree()
            workflow_id = WorkflowId("process-ticket-128")

            with (
                mock.patch.object(
                    MERGE_CLEANUP.MergedWorktreeCleanup,
                    "complete",
                    side_effect=SimulatedProcessCrash,
                ),
                self.assertRaises(SimulatedProcessCrash),
            ):
                MERGE_CLEANUP.MergeCleanupApplication().run(
                    environment={"CODEX_THREAD_ID": "owner-thread"},
                    cwd=fixture.worktree,
                    workflow_id=workflow_id,
                    base_branch="trunk",
                    remote_ref="origin/trunk",
                )

            foreign = registry.reserve_cleanup(
                active,
                planned_fencing_token="foreign-reservation-token",
            )
            registry.complete_cleanup(foreign)
            recreated = registry.claim(
                WorktreeClaim(
                    worktree_id=identity.worktree_id,
                    path=identity.path,
                    session_id=active.session_id,
                    actor_id=active.actor_id,
                )
            )
            registry.reserve_cleanup(
                recreated,
                planned_fencing_token="recreated-foreign-token",
            )

            with self.assertRaises(MERGE_CLEANUP.MergeCleanupPlanConflict):
                MERGE_CLEANUP.MergeCleanupApplication().run(
                    environment={"CODEX_THREAD_ID": "owner-thread"},
                    cwd=fixture.repo,
                    workflow_id=workflow_id,
                    base_branch="trunk",
                    remote_ref="origin/trunk",
                )

            self.assertTrue(fixture.worktree.is_dir())
            self.assertFalse(fixture.cleanup_receipt.exists())

    def test_root_branch_is_rechecked_at_every_destructive_boundary(self) -> None:
        """Reservation 뒤, merge 직전, receipt 직전 root branch 전환을 모두 거부합니다."""
        stages = ("after-reservation", "before-merge", "before-receipt")
        for stage in stages:
            with self.subTest(stage=stage), MergeCleanupFixture() as fixture:
                fixture.claim_worktree()
                fixture.create_root_branch("unexpected-root")
                if stage == "after-reservation":
                    original = MERGE_CLEANUP.WorktreeRegistry.reserve_cleanup

                    def reserve_then_switch(
                        registry: WorktreeRegistry,
                        claim: WorktreeClaim,
                        *,
                        planned_fencing_token: str | None = None,
                        _original: Callable[..., WorktreeClaim] = original,
                    ) -> WorktreeClaim:
                        """Reservation commit 직후 root branch를 전환합니다."""
                        reserved = _original(
                            registry,
                            claim,
                            planned_fencing_token=planned_fencing_token,
                        )
                        fixture.switch_root_branch("unexpected-root")
                        return reserved

                    patcher = mock.patch.object(
                        MERGE_CLEANUP.WorktreeRegistry,
                        "reserve_cleanup",
                        new=reserve_then_switch,
                    )
                elif stage == "before-merge":
                    original_refresh = MERGE_CLEANUP.MergedWorktreeCleanup._refresh_remote_refs

                    def refresh_then_switch(
                        cleanup: object,
                        _original: Callable[[object], None] = original_refresh,
                    ) -> None:
                        """Remote refresh 직후 root branch를 전환합니다."""
                        _original(cleanup)
                        fixture.switch_root_branch("unexpected-root")

                    patcher = mock.patch.object(
                        MERGE_CLEANUP.MergedWorktreeCleanup,
                        "_refresh_remote_refs",
                        new=refresh_then_switch,
                    )
                else:
                    original_receipt = MERGE_CLEANUP.MergedWorktreeCleanup._build_receipt

                    def switch_then_receipt(
                        cleanup: object,
                        _original: Callable[[object], dict[str, object]] = original_receipt,
                    ) -> dict[str, object]:
                        """Final receipt read-back 직전에 root branch를 전환합니다."""
                        fixture.switch_root_branch("unexpected-root")
                        return _original(cleanup)

                    patcher = mock.patch.object(
                        MERGE_CLEANUP.MergedWorktreeCleanup,
                        "_build_receipt",
                        new=switch_then_receipt,
                    )

                with patcher, self.assertRaises(MERGE_CLEANUP.MergeCleanupPlanConflict):
                    MERGE_CLEANUP.MergeCleanupApplication().run(
                        environment={"CODEX_THREAD_ID": "owner-thread"},
                        cwd=fixture.worktree,
                        workflow_id=WorkflowId("process-ticket-128"),
                        base_branch="trunk",
                        remote_ref="origin/trunk",
                    )

                self.assertFalse(fixture.cleanup_receipt.exists())

    def test_claim_release_recovery_fetches_and_syncs_latest_remote_head(self) -> None:
        """Released claim recovery도 persisted intent 아래 latest remote를 다시 sync합니다."""
        with MergeCleanupFixture() as fixture:
            identity, _claim, registry = fixture.claim_worktree()
            workflow_id = WorkflowId("process-ticket-128")

            with (
                mock.patch.object(
                    MERGE_CLEANUP.MergedWorktreeCleanup,
                    "_build_receipt",
                    side_effect=SimulatedProcessCrash,
                ),
                self.assertRaises(SimulatedProcessCrash),
            ):
                MERGE_CLEANUP.MergeCleanupApplication().run(
                    environment={"CODEX_THREAD_ID": "owner-thread"},
                    cwd=fixture.worktree,
                    workflow_id=workflow_id,
                    base_branch="trunk",
                    remote_ref="origin/trunk",
                )

            with self.assertRaises(WorktreeNotClaimed):
                registry.get(identity.worktree_id)
            fixture.publish_trunk_commit()

            receipt = MERGE_CLEANUP.MergeCleanupApplication().run(
                environment={"CODEX_THREAD_ID": "owner-thread"},
                cwd=fixture.repo,
                workflow_id=workflow_id,
                base_branch="trunk",
                remote_ref="origin/trunk",
            )

            self.assertEqual(fixture.remote_trunk_head(), receipt["root_head"])
            self.assertEqual(fixture.remote_trunk_head(), fixture.git("rev-parse", "HEAD"))

    def test_branch_delete_compare_and_swap_preserves_a_concurrently_moved_ref(self) -> None:
        """Worktree 제거 뒤 ticket ref가 바뀌면 stale cleanup이 새 ref를 지우지 않습니다."""
        with MergeCleanupFixture() as fixture:
            identity, _claim, registry = fixture.claim_worktree()
            replacement_oid = fixture.create_commit_object("concurrent ticket ref")
            original_delete = (
                MERGE_CLEANUP.MergedWorktreeCleanup._delete_ticket_branch_compare_and_swap
            )

            def move_ref_then_delete(cleanup: object) -> None:
                """Branch delete CAS 직전에 ticket ref를 새 commit으로 이동합니다."""
                fixture.git_with_dir(
                    "update-ref",
                    "refs/heads/task/128",
                    replacement_oid,
                )
                original_delete(cleanup)

            with (
                mock.patch.object(
                    MERGE_CLEANUP.MergedWorktreeCleanup,
                    "_delete_ticket_branch_compare_and_swap",
                    new=move_ref_then_delete,
                ),
                self.assertRaises(MERGE_CLEANUP.MergeCleanupPlanConflict),
            ):
                MERGE_CLEANUP.MergeCleanupApplication().run(
                    environment={"CODEX_THREAD_ID": "owner-thread"},
                    cwd=fixture.worktree,
                    workflow_id=WorkflowId("process-ticket-128"),
                    base_branch="trunk",
                    remote_ref="origin/trunk",
                )

            self.assertFalse(fixture.worktree.exists())
            self.assertEqual(
                replacement_oid,
                fixture.git_with_dir("rev-parse", "refs/heads/task/128"),
            )
            self.assertEqual(
                WorktreeClaimStatus.CLEANUP_RESERVED,
                registry.get(identity.worktree_id).status,
            )
            self.assertFalse(fixture.cleanup_receipt.exists())


class SimulatedProcessCrash(RuntimeError):
    """Cleanup external effects 뒤 process termination을 재현합니다."""


class MergeCleanupFixture:
    """Root, remote, publisher, linked worktree를 가진 Git fixture입니다."""

    def __enter__(self) -> Self:
        """격리된 root, remote, publisher, ticket worktree를 준비합니다.

        Returns:
            초기화된 fixture 자신입니다.
        """
        self._temporary_directory = TemporaryDirectory()
        self.root = Path(self._temporary_directory.name)
        self.repo = self.root / "repo"
        self.remote = self.root / "remote.git"
        self.publisher = self.root / "publisher"
        self._git_process("init", "-b", "trunk", str(self.repo))
        self._configure(self.repo)
        (self.repo / ".gitignore").write_text(
            ".tasks/\n.agents/worktrees/\n.agents/runs/\n.agents/resources/\n",
            encoding="utf-8",
        )
        (self.repo / "README.md").write_text("base\n", encoding="utf-8")
        self.git("add", ".gitignore", "README.md")
        self.git("commit", "--no-verify", "-m", "seed")
        self._git_process("clone", "--bare", str(self.repo), str(self.remote))
        self.git("remote", "add", "origin", str(self.remote))
        self.git("fetch", "origin")
        self.worktree = self.repo / ".tasks/128"
        self.git("worktree", "add", "-b", "task/128", str(self.worktree), "trunk")
        identity = WorktreeIdentityResolver().resolve(self.worktree)
        key = hashlib.sha256(str(identity.worktree_id).encode()).hexdigest()
        self.cleanup_receipt = self.repo / ".git/neurath-cleanup" / f"{key}.json"
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        """Fixture의 임시 directory를 정리합니다.

        Args:
            exc_type: Context 내부 예외 타입입니다.
            exc_value: Context 내부 예외 값입니다.
            traceback: Context 내부 예외 traceback입니다.
        """
        self._temporary_directory.cleanup()

    def publish_trunk_commit(self) -> None:
        """Remote trunk을 root보다 한 commit 앞서게 만듭니다."""
        self._git_process("clone", str(self.remote), str(self.publisher))
        self._configure(self.publisher)
        (self.publisher / "published.txt").write_text("published\n", encoding="utf-8")
        self._git_process("-C", str(self.publisher), "add", "published.txt")
        self._git_process(
            "-C",
            str(self.publisher),
            "commit",
            "--no-verify",
            "-m",
            "publish",
        )
        self._git_process("-C", str(self.publisher), "push", "origin", "trunk")

    def publish_remote_ref(self, branch: str) -> None:
        """Remote branch를 만든 뒤 root에 tracking ref를 materialize합니다."""
        self.create_upstream_ref(branch)
        self.git("fetch", "origin")

    def create_upstream_ref(self, branch: str) -> None:
        """Root tracking ref를 건드리지 않고 upstream branch를 생성합니다."""
        trunk_head = self.git("rev-parse", "trunk")
        self._git_process(
            f"--git-dir={self.remote}",
            "update-ref",
            f"refs/heads/{branch}",
            trunk_head,
        )

    def delete_upstream_ref(self, branch: str) -> None:
        """Root tracking ref는 유지한 채 upstream branch만 삭제합니다."""
        self._git_process(
            f"--git-dir={self.remote}",
            "update-ref",
            "-d",
            f"refs/heads/{branch}",
        )

    def claim_worktree(
        self,
        *,
        issue_number: int = 128,
        workflow_id: WorkflowId | None = None,
    ) -> tuple[CanonicalWorktreeIdentity, WorktreeClaim, WorktreeRegistry]:
        """Canonical session actor에게 fixture linked worktree를 claim합니다."""
        locator = SessionLocator.from_worktree(self.worktree)
        session_id = SessionId("owner-thread")
        actor_id = ActorId("codex:session:owner-thread")
        workflow_id = workflow_id or WorkflowId("process-ticket-128")
        kernel = SessionKernel(locator)
        kernel.apply(
            SessionStarted(
                session_id=session_id,
                resume_id=ResumeId("owner-thread"),
                runtime=SessionRuntime.CODEX,
                root_actor_id=actor_id,
                idempotency_key="fixture:session-start",
            )
        )
        kernel.apply(
            WorkflowStarted(
                session_id=session_id,
                workflow_id=workflow_id,
                owner_actor_id=actor_id,
                kind="process-ticket",
                goal=None,
                payload={"skill_state": {}},
                idempotency_key=f"fixture:workflow-start:{workflow_id}",
            )
        )
        identity = WorktreeIdentityResolver().resolve(self.worktree_for(issue_number))
        registry = WorktreeRegistry(locator)
        claim = registry.claim(
            WorktreeClaim(
                worktree_id=identity.worktree_id,
                path=identity.path,
                session_id=session_id,
                actor_id=actor_id,
            )
        )
        return identity, claim, registry

    def create_worktree(self, issue_number: int) -> Path:
        """추가 process-ticket linked worktree를 생성합니다."""
        worktree = self.worktree_for(issue_number)
        self.git(
            "worktree",
            "add",
            "-b",
            f"task/{issue_number}",
            str(worktree),
            "trunk",
        )
        return worktree

    def commit_ticket_change(self, issue_number: int, filename: str) -> None:
        """Ticket worktree에 clean late commit을 생성합니다."""
        worktree = self.worktree_for(issue_number)
        (worktree / filename).write_text("late\n", encoding="utf-8")
        self._git_process("-C", str(worktree), "add", filename)
        self._git_process(
            "-C",
            str(worktree),
            "commit",
            "--no-verify",
            "-m",
            "late ticket commit",
        )

    def create_root_branch(self, branch: str) -> None:
        """Root branch race용 local branch를 생성합니다."""
        self.git("branch", branch)

    def switch_root_branch(self, branch: str) -> None:
        """Root checkout을 지정한 branch로 전환합니다."""
        self.git("switch", branch)

    def remote_trunk_head(self) -> str:
        """Bare upstream의 actual trunk HEAD를 반환합니다."""
        return self._git_process(f"--git-dir={self.remote}", "rev-parse", "trunk")

    def create_commit_object(self, message: str) -> str:
        """Ref race를 재현할 새 commit object를 현재 object database에 생성합니다."""
        return self.git(
            "commit-tree",
            "HEAD^{tree}",
            "-p",
            "HEAD",
            "-m",
            message,
        )

    def worktree_for(self, issue_number: int) -> Path:
        """Issue 번호의 canonical linked worktree path를 반환합니다."""
        return self.repo / f".tasks/{issue_number}"

    def git(self, *args: str) -> str:
        """Root worktree를 대상으로 Git command를 실행합니다."""
        return self._git_process("-C", str(self.repo), *args)

    def git_with_dir(self, *args: str) -> str:
        """Root working-tree 인식과 무관하게 common Git dir를 검사합니다."""
        return self._git_process(f"--git-dir={self.repo / '.git'}", *args)

    def cleanup_intent(self, workflow_id: WorkflowId) -> object:
        """Exact workflow skill_state의 current cleanup intent를 반환합니다."""
        locator = SessionLocator.from_worktree(self.repo)
        workflow = SessionKernel(locator).inspect(SessionId("owner-thread")).workflows[workflow_id]
        skill_state = workflow.payload["skill_state"]
        assert isinstance(skill_state, dict)
        return skill_state.get("merge_cleanup_intent")

    def _configure(self, repository: Path) -> None:
        self._git_process("-C", str(repository), "config", "user.email", "test@example.invalid")
        self._git_process("-C", str(repository), "config", "user.name", "Neurath Harness Test")

    def _git_process(self, *args: str) -> str:
        environment = os.environ.copy()
        for name in (
            "GIT_DIR",
            "GIT_WORK_TREE",
            "GIT_INDEX_FILE",
            "GIT_PREFIX",
            "GIT_COMMON_DIR",
        ):
            environment.pop(name, None)
        result = subprocess.run(
            ["git", *args],
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

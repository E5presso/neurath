"""Session-scoped rehydration과 explicit lifecycle의 목표 계약입니다."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.agent_harness.enclave_store import EnclaveFact, EnclaveSourceKind, EnclaveStore
from scripts.agent_harness.runtime_database import RuntimeDatabase
from scripts.agent_harness.material_action import (
    AdaptiveActionBinding,
    MaterialActionBatch,
    MaterialActionKind,
    MaterialActionResolution,
    ObservableDeltaKind,
    ObservableExpectation,
    ObservableObservation,
    ToolReceipt,
    ToolReceiptOutcome,
)
from scripts.agent_harness.runtime_adapter import (
    LifecycleCause,
    RuntimeCapability,
    RuntimeEnvelope,
    RuntimeProvenance,
)
from scripts.agent_harness.session_kernel import (
    ActorId,
    ActorKind,
    ActorStarted,
    ActorStatus,
    DelegationAssigned,
    DelegationId,
    ForegroundTurnPrompted,
    ForegroundTurnProvisioned,
    MaterialActionPrepared,
    MaterialActionResolved,
    MaterialActionToolObserved,
    MaterialActionToolStarted,
    OutboxEffect,
    ProcessState,
    ResumeId,
    SessionId,
    SessionEnded,
    SessionKernel,
    SessionLocator,
    SessionRuntime,
    SessionStarted,
    TurnId,
    WorkflowId,
    WorkflowStarted,
)
from scripts.agent_harness.session_rehydration import (
    ForkLineage,
    HandoffProof,
    LifecycleConflict,
    RehydrationDiagnostic,
    RehydrationStatus,
    SessionContextRenderer,
    SessionLifecycle,
    SessionRehydrator,
    StaleFencingTokenError,
)
from scripts.agent_harness.worktree_registry import WorktreeClaim


class SessionRehydrationTest(unittest.TestCase):
    """Exact-session context injection과 lifecycle fencing을 검증합니다."""

    def setUp(self) -> None:
        """격리된 repository control root와 canonical stores를 준비합니다."""
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.addCleanup(self.directory.cleanup)
        self.locator = SessionLocator(self.root)
        self.kernel = SessionKernel(self.locator)
        self.enclaves = EnclaveStore(self.locator, max_bytes=4096)
        self.rehydrator = SessionRehydrator(self.locator, self.enclaves)
        self.lifecycle = SessionLifecycle(self.locator, self.enclaves)

    def write_session(self, session_id: str, fact: str, *, status: str = "active") -> None:
        """Public kernel/enclave APIs로 current SQLite session fixture를 기록합니다."""
        identity = SessionId(session_id)
        actor = ActorId(f"codex:session:{session_id}")
        self.kernel.apply(SessionStarted(
            session_id=identity,
            resume_id=ResumeId(session_id),
            runtime=SessionRuntime.CODEX,
            root_actor_id=actor,
            idempotency_key=f"fixture-start:{session_id}",
        ))
        current = self.enclaves.read(identity)
        self.enclaves.set(
            identity,
            actor,
            "invariant",
            EnclaveFact(
                value=fact,
                source_kind=EnclaveSourceKind.USER,
                source_turn_id=TurnId("turn-1"),
            ),
            expected_digest=current.digest,
        )
        if status == "ended":
            self.kernel.apply(SessionEnded(
                session_id=identity,
                actor_id=actor,
                idempotency_key=f"fixture-end:{session_id}",
            ))
        elif status != "active":
            raise ValueError(f"unsupported fixture status: {status}")

    def envelope(
        self,
        session_id: str,
        cause: LifecycleCause,
        *,
        capabilities: frozenset[RuntimeCapability] | None = None,
    ) -> RuntimeEnvelope:
        """Runtime-neutral lifecycle envelope를 만듭니다."""
        return RuntimeEnvelope(
            runtime=SessionRuntime.CODEX,
            session_id=SessionId(session_id),
            resume_id=ResumeId(session_id),
            actor_id=ActorId(f"codex:session:{session_id}"),
            parent_actor_id=None,
            cause=cause,
            capabilities=(
                frozenset({RuntimeCapability.SESSION_START_ADDITIONAL_CONTEXT})
                if capabilities is None
                else capabilities
            ),
            provenance=RuntimeProvenance(
                event_name="SessionStart",
                raw_session_id=session_id,
                raw_resume_id=session_id,
                raw_actor_id=None,
                raw_parent_actor_id=None,
            ),
        )

    def prepare_material_action(
        self,
        session_id: str,
        actor_id: ActorId,
        *,
        batch_id: str,
        sequence: int = 1,
        target_name: str = "material-target.txt",
    ) -> tuple[str, str]:
        """Exact actor turn에 bounded local material-action batch를 준비합니다."""
        target = str((self.root / target_name).resolve())
        expected_digest = hashlib.sha256(batch_id.encode("utf-8")).hexdigest()
        self.kernel.apply(
            ForegroundTurnProvisioned(
                session_id=SessionId(session_id),
                actor_id=actor_id,
                idempotency_key=f"turn:provision:{batch_id}",
            )
        )
        self.kernel.apply(
            ForegroundTurnPrompted(
                session_id=SessionId(session_id),
                actor_id=actor_id,
                vendor_turn_id=None,
                idempotency_key=f"turn:prompt:{batch_id}",
            )
        )
        turn = self.kernel.inspect(SessionId(session_id)).foreground_turns[actor_id]
        self.kernel.apply(
            MaterialActionPrepared(
                session_id=SessionId(session_id),
                actor_id=actor_id,
                batch_id=batch_id,
                sequence=sequence,
                expected_turn_generation=turn.generation,
                expected_turn_revision=turn.revision,
                kind=MaterialActionKind.LOCAL_MUTATION,
                targets=(target,),
                expectations=(
                    ObservableExpectation(
                        observable_id=target,
                        baseline_digest=None,
                        expected_delta=ObservableDeltaKind.CREATED,
                        expected_digest=expected_digest,
                    ),
                ),
                adaptive_binding=None,
                idempotency_key=f"material:prepare:{batch_id}",
            )
        )
        return target, expected_digest

    def resolve_material_action(
        self,
        session_id: str,
        actor_id: ActorId,
        *,
        batch_id: str,
        target: str,
        expected_digest: str,
    ) -> None:
        """Matching receipt와 delta를 기록해 prepared batch를 완료합니다."""
        request_digest = hashlib.sha256(f"request:{batch_id}".encode()).hexdigest()
        self.kernel.apply(
            MaterialActionToolStarted(
                session_id=SessionId(session_id),
                actor_id=actor_id,
                batch_id=batch_id,
                expected_batch_revision=0,
                invocation_id=f"tool:{batch_id}",
                tool_name="apply_patch",
                request_digest=request_digest,
                targets=(target,),
                idempotency_key=f"material:start:{batch_id}",
            )
        )
        self.kernel.apply(
            MaterialActionToolObserved(
                session_id=SessionId(session_id),
                actor_id=actor_id,
                batch_id=batch_id,
                expected_batch_revision=1,
                invocation_id=f"tool:{batch_id}",
                receipt=ToolReceipt(
                    receipt_id=f"post-tool:{batch_id}",
                    request_digest=request_digest,
                    outcome=ToolReceiptOutcome.SUCCEEDED,
                    output_digest=hashlib.sha256(b"bounded-output").hexdigest(),
                    observations=(
                        ObservableObservation(
                            observable_id=target,
                            current_digest=expected_digest,
                        ),
                    ),
                ),
                idempotency_key=f"material:observe:{batch_id}",
            )
        )
        self.kernel.apply(
            MaterialActionResolved(
                session_id=SessionId(session_id),
                actor_id=actor_id,
                batch_id=batch_id,
                expected_batch_revision=2,
                resolution=MaterialActionResolution.COMPLETED,
                idempotency_key=f"material:resolve:{batch_id}",
            )
        )

    def test_compact_injects_only_the_exact_session_as_additional_context(self) -> None:
        """Session A compact는 A enclave만 additionalContext로 반환합니다."""
        self.write_session("session-a", "A 전용 사실")
        self.write_session("session-b", "B 전용 사실")
        self.kernel.apply(
            WorkflowStarted(
                session_id=SessionId("session-a"),
                workflow_id=WorkflowId("workflow-a"),
                owner_actor_id=ActorId("codex:session:session-a"),
                kind="process-ticket",
                goal="A 세션 북극성",
                payload={},
                idempotency_key="workflow-a:start",
            )
        )
        self.kernel.apply(
            WorkflowStarted(
                session_id=SessionId("session-b"),
                workflow_id=WorkflowId("workflow-b"),
                owner_actor_id=ActorId("codex:session:session-b"),
                kind="process-ticket",
                goal="B 세션 북극성",
                payload={},
                idempotency_key="workflow-b:start",
            )
        )

        decision = self.rehydrator.rehydrate(self.envelope("session-a", LifecycleCause.COMPACT))

        self.assertEqual(RehydrationStatus.READY, decision.status)
        self.assertEqual("SessionStart", decision.hook_event_name)
        additional_context = decision.additional_context
        self.assertIsNotNone(additional_context)
        assert additional_context is not None
        self.assertIn("A 전용 사실", additional_context)
        self.assertIn("A 세션 북극성", additional_context)
        self.assertNotIn("B 전용 사실", additional_context)
        self.assertNotIn("B 세션 북극성", additional_context)

    def test_compact_injects_only_bounded_current_actor_open_material_action(self) -> None:
        """Open batch rehydration은 current actor의 allowlisted intent field만 복원합니다."""
        self.write_session("session-a", "A 전용 사실")
        actor_id = ActorId("codex:session:session-a")
        target, expected_digest = self.prepare_material_action(
            "session-a",
            actor_id,
            batch_id="batch-current",
        )
        batch = self.kernel.inspect(SessionId("session-a")).material_actions[actor_id]
        request_digest = hashlib.sha256(b"private-request").hexdigest()
        self.kernel.apply(
            MaterialActionToolStarted(
                session_id=SessionId("session-a"),
                actor_id=actor_id,
                batch_id=batch.batch_id,
                expected_batch_revision=batch.revision,
                invocation_id="invocation-private",
                tool_name="RAW_COMMAND_SHOULD_NOT_LEAK",
                request_digest=request_digest,
                targets=(target,),
                idempotency_key="material:start:private",
            )
        )

        decision = self.rehydrator.rehydrate(self.envelope("session-a", LifecycleCause.COMPACT))

        self.assertEqual(RehydrationStatus.READY, decision.status)
        context = decision.additional_context
        self.assertIsNotNone(context)
        assert context is not None
        encoded = context.split("<neurath-open-material-action>", 1)[1].split(
            "</neurath-open-material-action>", 1
        )[0]
        self.assertEqual(
            {
                "adaptive_binding": None,
                "batch_id": "batch-current",
                "expectation_ids": [target],
                "kind": "local-mutation",
                "revision": 1,
                "sequence": 1,
                "status": "open",
                "targets": [target],
            },
            json.loads(encoded),
        )
        self.assertNotIn("RAW_COMMAND_SHOULD_NOT_LEAK", context)
        self.assertNotIn("invocation-private", context)
        self.assertNotIn(request_digest, context)
        self.assertNotIn(expected_digest, context)

    def test_rehydration_omits_resolved_and_foreign_actor_material_actions(self) -> None:
        """Resolved latest batch와 다른 actor의 open batch는 current context에 주입하지 않습니다."""
        self.write_session("resolved", "resolved fact")
        root_id = ActorId("codex:session:resolved")
        target, expected_digest = self.prepare_material_action(
            "resolved",
            root_id,
            batch_id="batch-resolved",
        )
        self.resolve_material_action(
            "resolved",
            root_id,
            batch_id="batch-resolved",
            target=target,
            expected_digest=expected_digest,
        )
        resolved = self.rehydrator.rehydrate(self.envelope("resolved", LifecycleCause.COMPACT))
        self.assertNotIn("neurath-open-material-action", resolved.additional_context or "")

        self.write_session("foreign", "foreign fact")
        foreign_root = ActorId("codex:session:foreign")
        worker_id = ActorId("codex:worker")
        self.kernel.apply(
            ActorStarted(
                session_id=SessionId("foreign"),
                actor_id=worker_id,
                parent_actor_id=foreign_root,
                kind=ActorKind.SUBAGENT,
                idempotency_key="foreign:worker:start",
            )
        )
        foreign_target, _digest = self.prepare_material_action(
            "foreign",
            worker_id,
            batch_id="batch-foreign",
            target_name="foreign-secret.txt",
        )

        root_context = self.rehydrator.rehydrate(
            self.envelope("foreign", LifecycleCause.COMPACT)
        ).additional_context

        self.assertNotIn("neurath-open-material-action", root_context or "")
        self.assertNotIn(foreign_target, root_context or "")

    def test_material_action_summary_preserves_adaptive_goal_provenance(self) -> None:
        """Adaptive binding은 raw reasoning 없이 workflow와 goal fingerprint만 보존합니다."""
        self.write_session("session-a", "A 전용 사실")
        actor_id = ActorId("codex:session:session-a")
        self.kernel.apply(
            ForegroundTurnProvisioned(
                session_id=SessionId("session-a"),
                actor_id=actor_id,
                idempotency_key="adaptive:turn:provision",
            )
        )
        self.kernel.apply(
            ForegroundTurnPrompted(
                session_id=SessionId("session-a"),
                actor_id=actor_id,
                vendor_turn_id=None,
                idempotency_key="adaptive:turn",
            )
        )
        state = self.kernel.inspect(SessionId("session-a"))
        turn = state.foreground_turns[actor_id]
        goal_fingerprint = hashlib.sha256(b"goal").hexdigest()
        action = MaterialActionBatch.prepare(
            batch_id="batch-adaptive",
            sequence=1,
            session_id="session-a",
            actor_id=str(actor_id),
            turn_generation=turn.generation,
            turn_revision=turn.revision,
            kind=MaterialActionKind.SEMANTIC_DECISION,
            targets=("decision:architecture",),
            expectations=(
                ObservableExpectation(
                    observable_id="decision:architecture",
                    baseline_digest=hashlib.sha256(b"before").hexdigest(),
                    expected_delta=ObservableDeltaKind.CHANGED,
                    expected_digest=hashlib.sha256(b"after").hexdigest(),
                ),
            ),
            adaptive_binding=AdaptiveActionBinding(
                workflow_id="adaptive-workflow",
                workflow_revision=7,
                goal_fingerprint=goal_fingerprint,
            ),
        )
        projected = ProcessState(
            state.revision,
            state.session,
            state.actors,
            state.workflows,
            state.delegations,
            state.resources,
            state.mailboxes,
            state.incidents,
            state.outbox,
            state.foreground_turns,
            {actor_id: action},
        )

        context = SessionContextRenderer().render(
            self.enclaves.read(SessionId("session-a")),
            projected,
            self.envelope("session-a", LifecycleCause.COMPACT),
        )
        encoded = context.split("<neurath-open-material-action>", 1)[1].split(
            "</neurath-open-material-action>", 1
        )[0]
        summary = json.loads(encoded)

        self.assertEqual(
            {
                "goal_fingerprint": goal_fingerprint,
                "workflow_id": "adaptive-workflow",
                "workflow_revision": 7,
            },
            summary["adaptive_binding"],
        )
        self.assertNotIn("reasoning", context.lower())

    def test_subagent_start_injects_only_target_assignments(self) -> None:
        """Subagent는 같은 session enclave와 자신에게 배정된 작업만 전달받습니다."""
        self.write_session("session-a", "공통 세션 불변식")
        root_actor = ActorId("codex:session:session-a")
        target_actor = ActorId("codex:worker-target")
        other_actor = ActorId("codex:worker-other")
        for actor_id in (target_actor, other_actor):
            self.kernel.apply(
                ActorStarted(
                    session_id=SessionId("session-a"),
                    actor_id=actor_id,
                    parent_actor_id=root_actor,
                    kind=ActorKind.SUBAGENT,
                    idempotency_key=f"actor-started:{actor_id}",
                )
            )
        for delegation_id, actor_id, assignment in (
            ("delegation-target", target_actor, "target 전용 작업"),
            ("delegation-other", other_actor, "other 전용 작업"),
        ):
            self.kernel.apply(
                DelegationAssigned(
                    session_id=SessionId("session-a"),
                    delegation_id=DelegationId(delegation_id),
                    owner_actor_id=root_actor,
                    target_actor_id=actor_id,
                    assignment=assignment,
                    idempotency_key=f"delegation:{delegation_id}",
                )
            )
        envelope = RuntimeEnvelope(
            runtime=SessionRuntime.CODEX,
            session_id=SessionId("session-a"),
            resume_id=ResumeId("session-a"),
            actor_id=target_actor,
            parent_actor_id=root_actor,
            cause=LifecycleCause.SUBAGENT_START,
            capabilities=frozenset({RuntimeCapability.SUBAGENT_START_ADDITIONAL_CONTEXT}),
            provenance=RuntimeProvenance(
                event_name="SubagentStart",
                raw_session_id="session-a",
                raw_resume_id="session-a",
                raw_actor_id="worker-target",
                raw_parent_actor_id="session:session-a",
            ),
        )

        decision = self.rehydrator.rehydrate(envelope)

        self.assertEqual(RehydrationStatus.READY, decision.status)
        context = decision.additional_context
        self.assertIsNotNone(context)
        assert context is not None
        self.assertIn("공통 세션 불변식", context)
        self.assertIn("target 전용 작업", context)
        self.assertNotIn("other 전용 작업", context)

    def test_normal_turn_never_reinjects_enclave(self) -> None:
        """Enclave는 정상 turn마다 반복 주입되지 않습니다."""
        self.write_session("session-a", "A 전용 사실")

        decision = self.rehydrator.rehydrate(self.envelope("session-a", LifecycleCause.NORMAL_TURN))

        self.assertEqual(RehydrationStatus.SKIPPED, decision.status)
        self.assertIsNone(decision.additional_context)

    def test_unavailable_capability_is_blocked_without_global_fallback(self) -> None:
        """AdditionalContext capability 부재는 다른 session 주입으로 우회하지 않습니다."""
        self.write_session("session-a", "A 전용 사실")
        self.write_session("session-b", "절대 fallback하면 안 되는 B 사실")

        decision = self.rehydrator.rehydrate(
            self.envelope(
                "session-a",
                LifecycleCause.COMPACT,
                capabilities=frozenset(),
            )
        )

        self.assertEqual(RehydrationStatus.BLOCKED, decision.status)
        self.assertEqual(RehydrationDiagnostic.CAPABILITY_UNAVAILABLE, decision.diagnostic)
        self.assertIsNone(decision.additional_context)

    def test_terminal_corrupt_and_orphan_sessions_never_fallback(self) -> None:
        """무효 exact session은 다른 active session을 찾지 않고 typed diagnostic을 냅니다."""
        self.write_session("fallback", "fallback하면 안 되는 사실")
        self.write_session("terminal", "종료된 사실", status="ended")
        self.write_session("corrupt", "손상 전 사실")
        with RuntimeDatabase(self.root).connection() as db:
            changed = db.execute(
                "UPDATE runtime_records SET payload=? "
                "WHERE namespace='session' AND key='corrupt'",
                (b"{not-json",),
            )
            self.assertEqual(1, changed.rowcount)
        with RuntimeDatabase(self.root).transaction() as tx:
            tx.put("enclave", "orphan", b"{}", expected_revision=None)

        cases = (
            ("terminal", RehydrationDiagnostic.TERMINAL_SESSION),
            ("corrupt", RehydrationDiagnostic.CORRUPT_STATE),
            ("orphan", RehydrationDiagnostic.ORPHAN_SESSION),
        )
        for session_id, diagnostic in cases:
            with self.subTest(session_id=session_id):
                decision = self.rehydrator.rehydrate(
                    self.envelope(session_id, LifecycleCause.COMPACT)
                )
                self.assertNotEqual(RehydrationStatus.READY, decision.status)
                self.assertEqual(diagnostic, decision.diagnostic)
                self.assertIsNone(decision.additional_context)

    def test_fork_copies_one_snapshot_then_keeps_enclaves_independent(self) -> None:
        """증명된 fork는 enclave snapshot만 한 번 복사하고 파일을 공유하지 않습니다."""
        self.write_session("source", "원본 사실")

        receipt = self.lifecycle.fork(
            ForkLineage(
                runtime=SessionRuntime.CODEX,
                source_session_id=SessionId("source"),
                target_session_id=SessionId("forked"),
                provenance_id="thread-fork:source->forked",
            )
        )
        target = self.kernel.inspect(SessionId("forked"))
        before = self.enclaves.read(SessionId("forked"))
        changed = self.enclaves.set(SessionId("forked"), target.session.root_actor_id,
            "invariant", EnclaveFact(value="fork에서만 변경", source_kind=EnclaveSourceKind.USER,
                                    source_turn_id=TurnId("fork-update")),
            expected_digest=before.digest)
        self.assertEqual("fork에서만 변경", changed.facts["invariant"].value)

        self.assertEqual(SessionId("forked"), receipt.target_session_id)
        source_content = json.dumps(self.enclaves.read(SessionId("source")).to_payload(), ensure_ascii=False)
        self.assertIn("원본 사실", source_content)
        self.assertNotIn("fork에서만 변경", source_content)
        self.assertNotEqual(
            self.enclaves.read(SessionId("source")).digest,
            changed.digest,
        )
        target_state = self.kernel.inspect(SessionId("forked"))
        self.assertEqual(SessionId("source"), target_state.session.parent_session_id)
        self.assertEqual(
            "thread-fork:source->forked",
            target_state.session.lifecycle_provenance_id,
        )

    def test_fork_retry_completes_exact_initialized_lineage_in_one_snapshot_write(self) -> None:
        """Crash 후 retry는 같은 lineage의 빈 target enclave를 전체 snapshot으로 완성합니다."""
        self.write_session("source", "원본 사실")
        source_snapshot = self.enclaves.read(SessionId("source"))
        self.enclaves.set(
            SessionId("source"),
            ActorId("codex:session:source"),
            "second-invariant",
            EnclaveFact(
                value="둘째 사실",
                source_kind=EnclaveSourceKind.USER,
                source_turn_id=TurnId("turn-second"),
            ),
            expected_digest=source_snapshot.digest,
        )
        self.kernel.apply(
            SessionStarted(
                session_id=SessionId("forked"),
                resume_id=ResumeId("forked"),
                runtime=SessionRuntime.CODEX,
                root_actor_id=ActorId("codex:session:forked"),
                parent_session_id=SessionId("source"),
                lifecycle_provenance_id="fork-proof-1",
                idempotency_key="fork:fork-proof-1",
            )
        )

        receipt = self.lifecycle.fork(
            ForkLineage(
                runtime=SessionRuntime.CODEX,
                source_session_id=SessionId("source"),
                target_session_id=SessionId("forked"),
                provenance_id="fork-proof-1",
            )
        )

        target = self.enclaves.read(SessionId("forked"))
        self.assertEqual({"invariant", "second-invariant"}, set(target.facts))
        self.assertEqual(
            self.enclaves.read(SessionId("source")).digest, receipt.source_enclave_digest
        )

    def test_fork_rejects_existing_target_with_different_lineage_provenance(self) -> None:
        """Target identity가 같아도 persisted fork provenance가 다르면 retry로 가장하지 않습니다."""
        self.write_session("source", "원본 사실")
        self.kernel.apply(
            SessionStarted(
                session_id=SessionId("forked"),
                resume_id=ResumeId("forked"),
                runtime=SessionRuntime.CODEX,
                root_actor_id=ActorId("codex:session:forked"),
                parent_session_id=SessionId("source"),
                lifecycle_provenance_id="different-proof",
                idempotency_key="fork:different-proof",
            )
        )

        with self.assertRaises(LifecycleConflict):
            self.lifecycle.fork(
                ForkLineage(
                    runtime=SessionRuntime.CODEX,
                    source_session_id=SessionId("source"),
                    target_session_id=SessionId("forked"),
                    provenance_id="expected-proof",
                )
            )

        self.assertEqual({}, self.enclaves.read(SessionId("forked")).facts)

    def test_synthetic_handoff_retires_previous_actor(self) -> None:
        """Synthetic handoff는 lease 이전과 함께 이전 actor authority를 retire합니다."""
        self.write_session("session-a", "handoff 사실")
        old_owner = ActorId("codex:worker-old")
        new_owner = ActorId("codex:worker-new")
        root_actor = ActorId("codex:session:session-a")
        for actor_id in (old_owner, new_owner):
            self.kernel.apply(
                ActorStarted(
                    session_id=SessionId("session-a"),
                    actor_id=actor_id,
                    parent_actor_id=root_actor,
                    kind=ActorKind.SUBAGENT,
                    idempotency_key=f"actor-started:{actor_id}",
                )
            )
        worktree_path = self.root / ".agents/worktrees/worktree-17"
        worktree_path.mkdir(parents=True)
        lease = self.lifecycle.claim_worktree(
            SessionId("session-a"),
            old_owner,
            "worktree-17",
            worktree_path,
        )

        receipt = self.lifecycle.handoff(
            HandoffProof(
                session_id=SessionId("session-a"),
                worktree_id="worktree-17",
                previous_owner_id=old_owner,
                next_owner_id=new_owner,
                previous_fencing_token=lease.fencing_token,
                durable_flush_receipt="flush:worker-old:42",
                exact_resume_id=ResumeId("resume-worker-new"),
            )
        )

        self.assertEqual(new_owner, receipt.owner_actor_id)
        self.assertEqual(lease.epoch + 1, receipt.epoch)
        self.assertNotEqual(lease.fencing_token, receipt.fencing_token)
        state = self.kernel.inspect(SessionId("session-a"))
        self.assertEqual(ActorStatus.RETIRED, state.actors[old_owner].status)
        self.assertEqual(ActorStatus.ACTIVE, state.actors[new_owner].status)
        with self.assertRaises(StaleFencingTokenError):
            self.lifecycle.assert_mutation_allowed("worktree-17", old_owner, lease.fencing_token)

    def test_handoff_retry_after_lease_commit_retires_previous_actor(self) -> None:
        """Lease commit 직후 중단돼도 same proof retry가 retirement로 수렴합니다."""
        self.write_session("session-a", "handoff retry 사실")
        old_owner = ActorId("codex:worker-old")
        new_owner = ActorId("codex:worker-new")
        root_actor = ActorId("codex:session:session-a")
        for actor_id in (old_owner, new_owner):
            self.kernel.apply(
                ActorStarted(
                    session_id=SessionId("session-a"),
                    actor_id=actor_id,
                    parent_actor_id=root_actor,
                    kind=ActorKind.SUBAGENT,
                    idempotency_key=f"actor-started:{actor_id}",
                )
            )
        worktree_path = self.root / ".agents/worktrees/worktree-retry"
        worktree_path.mkdir(parents=True)
        lease = self.lifecycle.claim_worktree(
            SessionId("session-a"),
            old_owner,
            "worktree-retry",
            worktree_path,
        )
        proof = HandoffProof(
            session_id=SessionId("session-a"),
            worktree_id="worktree-retry",
            previous_owner_id=old_owner,
            next_owner_id=new_owner,
            previous_fencing_token=lease.fencing_token,
            durable_flush_receipt="flush:worker-old:retry",
            exact_resume_id=ResumeId("resume-worker-new"),
        )

        class InterruptAfterLeaseLifecycle(SessionLifecycle):
            """첫 retirement 직전 crash를 한 번 재현합니다."""

            def __init__(self, locator: SessionLocator, enclaves: EnclaveStore) -> None:
                """실제 lifecycle service에 one-shot retirement fault를 추가합니다.

                Args:
                    locator: Exact session과 resource registry locator입니다.
                    enclaves: Session fork context를 제공하는 canonical enclave store입니다.
                """
                super().__init__(locator, enclaves)
                self.interrupted = False

            def _retire_previous_actor(self, proof: HandoffProof) -> None:
                if not self.interrupted:
                    self.interrupted = True
                    raise OSError("simulated crash after lease commit")
                super()._retire_previous_actor(proof)

        lifecycle = InterruptAfterLeaseLifecycle(self.locator, self.enclaves)

        with self.assertRaises(OSError):
            lifecycle.handoff(proof)

        receipt = lifecycle.handoff(proof)
        state = self.kernel.inspect(SessionId("session-a"))

        self.assertEqual(new_owner, receipt.owner_actor_id)
        self.assertEqual(lease.epoch + 1, receipt.epoch)
        self.assertEqual(ActorStatus.RETIRED, state.actors[old_owner].status)
        self.assertEqual(ActorStatus.ACTIVE, state.actors[new_owner].status)
        self.assertEqual({}, state.outbox)

    def test_handoff_retry_does_not_recover_another_proof_for_same_target_actor(
        self,
    ) -> None:
        """Target actor와 previous lease가 같아도 다른 proof의 commit은 retry 성공이 아닙니다."""
        self.write_session("session-a", "handoff proof conflict 사실")
        old_owner = ActorId("codex:worker-old")
        new_owner = ActorId("codex:worker-new")
        root_actor = ActorId("codex:session:session-a")
        for actor_id in (old_owner, new_owner):
            self.kernel.apply(
                ActorStarted(
                    session_id=SessionId("session-a"),
                    actor_id=actor_id,
                    parent_actor_id=root_actor,
                    kind=ActorKind.SUBAGENT,
                    idempotency_key=f"actor-started:proof-conflict:{actor_id}",
                )
            )
        worktree_path = self.root / ".agents/worktrees/worktree-proof-conflict"
        worktree_path.mkdir(parents=True)
        lease = self.lifecycle.claim_worktree(
            SessionId("session-a"),
            old_owner,
            "worktree-proof-conflict",
            worktree_path,
        )
        proof_a = HandoffProof(
            session_id=SessionId("session-a"),
            worktree_id="worktree-proof-conflict",
            previous_owner_id=old_owner,
            next_owner_id=new_owner,
            previous_fencing_token=lease.fencing_token,
            durable_flush_receipt="flush:proof-a",
            exact_resume_id=ResumeId("resume:proof-a"),
        )
        proof_b = HandoffProof(
            session_id=SessionId("session-a"),
            worktree_id="worktree-proof-conflict",
            previous_owner_id=old_owner,
            next_owner_id=new_owner,
            previous_fencing_token=lease.fencing_token,
            durable_flush_receipt="flush:proof-b",
            exact_resume_id=ResumeId("resume:proof-b"),
        )

        class InterruptProofAAfterPrepare(SessionLifecycle):
            """Proof A의 outbox prepare 직후만 one-shot interruption을 발생시킵니다."""

            def __init__(self, locator: SessionLocator, enclaves: EnclaveStore) -> None:
                """Production lifecycle에 proof A전용 one-shot fault를 추가합니다.

                Args:
                    locator: Exact session과 resource registry locator입니다.
                    enclaves: Session lifecycle의 canonical enclave store입니다.
                """
                super().__init__(locator, enclaves)
                self.interrupted = False

            def _transfer_or_recover(
                self,
                current: WorktreeClaim,
                proof: HandoffProof,
                pending: OutboxEffect,
            ) -> WorktreeClaim:
                """Proof A prepare 후 lease CAS 전에 첫 실행만 중단합니다.

                Args:
                    current: Proof가 읽은 current worktree claim입니다.
                    proof: 현재 실행의 exact handoff proof입니다.
                    pending: Lease CAS 전에 commit된 recoverable effect입니다.

                Returns:
                    Fault 이후 retry에서 production transfer 결과를 반환합니다.
                """
                if proof is proof_a and not self.interrupted:
                    self.interrupted = True
                    raise OSError("simulated crash after proof A prepare")
                return super()._transfer_or_recover(current, proof, pending)

        lifecycle = InterruptProofAAfterPrepare(self.locator, self.enclaves)

        with self.assertRaises(OSError):
            lifecycle.handoff(proof_a)
        prepared_state = self.kernel.inspect(SessionId("session-a"))
        self.assertEqual(1, len(prepared_state.outbox))

        receipt_b = lifecycle.handoff(proof_b)
        state_after_b = self.kernel.inspect(SessionId("session-a"))
        self.assertEqual(new_owner, receipt_b.owner_actor_id)
        self.assertEqual(1, len(state_after_b.outbox))

        with self.assertRaises(StaleFencingTokenError):
            lifecycle.handoff(proof_a)

        final_state = self.kernel.inspect(SessionId("session-a"))
        self.assertEqual({}, final_state.outbox)
        lifecycle.assert_mutation_allowed(
            "worktree-proof-conflict",
            new_owner,
            receipt_b.fencing_token,
        )


if __name__ == "__main__":  # pragma: no cover - test entrypoint
    unittest.main()

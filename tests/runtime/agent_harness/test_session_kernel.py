"""SessionKernel의 session 격리와 원자적 상태 전이 계약을 검증합니다."""

from __future__ import annotations

import json
import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from scripts.agent_harness.session_kernel import (
    ActorId,
    ActorKind,
    ActorStarted,
    CommitStage,
    DelegationAssigned,
    DelegationId,
    ForegroundTurnPrompted,
    ForegroundTurnProvisioned,
    HarnessIncidentRecorded,
    HarnessIncidentResolved,
    HarnessIncidentStatus,
    HarnessRegressionReceipt,
    IncidentId,
    KernelEvent,
    ProcessState,
    ReservedSkillStateAdvanced,
    ResumeId,
    RevisionConflict,
    SessionId,
    SessionKernel,
    SessionLocator,
    SessionNotFound,
    SessionRuntime,
    SessionStarted,
    SessionStateReducer,
    SessionStateStore,
    TransitionRejected,
    WorkflowAdvanced,
    WorkflowId,
    WorkflowStarted,
)

CRASH_EXIT_CODE = 73


class RevisionAdvancingReducer(SessionStateReducer):
    """No-op candidate 반환 직전에 별도 store의 revision을 전진시키는 race fixture입니다."""

    def __init__(
        self,
        competing_store: SessionStateStore,
        competing_event: KernelEvent,
    ) -> None:
        """Reducer 계산과 no-op 반환 사이의 concurrent commit을 결정적으로 구성합니다.

        Args:
            competing_store: 같은 canonical snapshot에 별도 transaction을 수행할 store입니다.
            competing_event: Initial snapshot을 실제로 변경해 revision을 전진시킬 event입니다.
        """
        self._competing_store = competing_store
        self._competing_event = competing_event

    def reduce(self, state: ProcessState | None, event: KernelEvent) -> ProcessState:
        """원래 reduce 결과를 보존하면서 반환 직전 competing commit을 완료합니다.

        Args:
            state: Explicit compare가 처음 읽은 immutable session snapshot입니다.
            event: 기존 snapshot을 그대로 반환하게 할 idempotent event입니다.

        Returns:
            Competing revision 이전에 계산된 원래 reducer의 candidate입니다.
        """
        candidate = super().reduce(state, event)
        self._competing_store.transact(self._competing_event)
        return candidate


def _start_actor(
    control_root: str,
    session_id: str,
    actor_id: str,
    root_actor_id: str,
) -> int:
    """별도 process에서 subagent actor 하나를 durable state에 추가합니다."""
    kernel = SessionKernel(SessionLocator(Path(control_root)))
    state = kernel.apply(
        ActorStarted(
            session_id=SessionId(session_id),
            actor_id=ActorId(actor_id),
            parent_actor_id=ActorId(root_actor_id),
            kind=ActorKind.SUBAGENT,
            idempotency_key=f"actor-started:{actor_id}",
        )
    )
    return state.revision


def _assign_delegation(
    control_root: str,
    session_id: str,
    root_actor_id: str,
    target_actor_id: str,
    delegation_id: str,
) -> int:
    """별도 process에서 delegation 하나를 다른 delegation과 독립적으로 추가합니다."""
    kernel = SessionKernel(SessionLocator(Path(control_root)))
    state = kernel.apply(
        DelegationAssigned(
            session_id=SessionId(session_id),
            delegation_id=DelegationId(delegation_id),
            owner_actor_id=ActorId(root_actor_id),
            target_actor_id=ActorId(target_actor_id),
            assignment=f"assignment for {target_actor_id}",
            idempotency_key=f"delegation-assigned:{delegation_id}",
        )
    )
    return state.revision


def _compare_and_start_actor(
    control_root: str,
    session_id: str,
    actor_id: str,
    root_actor_id: str,
    expected_revision: int,
) -> str:
    """동일 revision에 대한 compare-and-transact 결과를 직렬화 가능한 값으로 반환합니다."""
    kernel = SessionKernel(SessionLocator(Path(control_root)))
    try:
        kernel.apply(
            ActorStarted(
                session_id=SessionId(session_id),
                actor_id=ActorId(actor_id),
                parent_actor_id=ActorId(root_actor_id),
                kind=ActorKind.SUBAGENT,
                idempotency_key=f"cas-actor-started:{actor_id}",
            ),
            expected_revision=expected_revision,
        )
    except RevisionConflict:
        return "conflict"
    return "committed"


def _terminate_before_replace(stage: CommitStage) -> None:
    """Canonical replace 직전에 process를 종료해 crash 경계를 재현합니다."""
    if stage is CommitStage.BEFORE_REPLACE:
        os._exit(CRASH_EXIT_CODE)


def _crash_actor_commit(
    process_state_path: str,
    session_id: str,
    actor_id: str,
    root_actor_id: str,
) -> None:
    """별도 process가 temporary snapshot fsync 뒤 canonical replace 전에 종료됩니다."""
    store = SessionStateStore(
        Path(process_state_path),
        commit_observer=_terminate_before_replace,
    )
    store.transact(
        ActorStarted(
            session_id=SessionId(session_id),
            actor_id=ActorId(actor_id),
            parent_actor_id=ActorId(root_actor_id),
            kind=ActorKind.SUBAGENT,
            idempotency_key=f"crashing-actor-started:{actor_id}",
        )
    )


class SessionKernelAcceptanceTest(TestCase):
    """H02, H03, H04, H06의 durable state 불변식을 검증합니다."""

    def setUp(self) -> None:
        """각 test가 독립된 repository control root를 사용하게 합니다."""
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.control_root = Path(self.temporary_directory.name)
        self.locator = SessionLocator(self.control_root)
        self.kernel = SessionKernel(self.locator)

    def start_session(
        self,
        session_id: str,
        root_actor_id: str,
        *,
        resume_id: str | None = None,
    ) -> None:
        """Workflow 없이 canonical session state와 root actor를 초기화합니다."""
        self.kernel.apply(
            SessionStarted(
                session_id=SessionId(session_id),
                resume_id=ResumeId(resume_id or f"resume:{session_id}"),
                runtime=SessionRuntime.CODEX,
                root_actor_id=ActorId(root_actor_id),
                idempotency_key=f"session-started:{session_id}",
            )
        )

    def test_session_start_separates_identity_without_creating_workflow_or_goal(self) -> None:
        """Session open은 session/resume/actor identity만 만들고 workflow나 goal을 생성하지 않습니다."""
        self.start_session("session-a", "codex:root-a", resume_id="opaque-resume-a")

        state = self.kernel.inspect(SessionId("session-a"))
        payload = state.to_payload()

        self.assertEqual(SessionId("session-a"), state.session.id)
        self.assertEqual(ResumeId("opaque-resume-a"), state.session.resume_id)
        self.assertEqual(ActorId("codex:root-a"), state.session.root_actor_id)
        self.assertNotEqual(state.session.id, state.session.root_actor_id)
        self.assertEqual({}, state.workflows)
        self.assertEqual({}, state.foreground_turns)
        self.assertNotIn("goal", payload)
        self.assertNotIn("north_star", payload)
        session_payload = payload["session"]
        self.assertIsInstance(session_payload, dict)
        if not isinstance(session_payload, dict):
            self.fail("serialized session must be an object")
        self.assertNotIn("goal", session_payload)
        self.assertEqual(
            {
                "actors",
                "delegations",
                "foreground_turns",
                "incidents",
                "mailboxes",
                "material_actions",
                "outbox",
                "resources",
                "revision",
                "schema",
                "session",
                "workflows",
            },
            set(payload),
        )

    def test_two_sessions_have_disjoint_canonical_state_and_no_missing_session_fallback(
        self,
    ) -> None:
        """같은 repo의 session들은 exact directory로 격리되며 missing lookup은 다른 state로 fallback하지 않습니다."""
        self.start_session("session-a", "codex:root-a")
        self.start_session("session-b", "codex:root-b")

        paths_a = self.locator.locate(SessionId("session-a"))
        paths_b = self.locator.locate(SessionId("session-b"))
        self.kernel.apply(
            ActorStarted(
                session_id=SessionId("session-a"),
                actor_id=ActorId("codex:worker-a"),
                parent_actor_id=ActorId("codex:root-a"),
                kind=ActorKind.SUBAGENT,
                idempotency_key="actor-started:worker-a",
            )
        )

        state_a = self.kernel.inspect(SessionId("session-a"))
        state_b = self.kernel.inspect(SessionId("session-b"))

        self.assertEqual(
            self.control_root / ".agents/runs/session-a/.process-state.json",
            paths_a.process_state,
        )
        self.assertEqual(
            self.control_root / ".agents/runs/session-a/enclave.json",
            paths_a.enclave,
        )
        self.assertNotEqual(paths_a.directory, paths_b.directory)
        self.assertTrue(SessionStateStore(paths_a.process_state).exists())
        self.assertFalse(paths_a.enclave.is_file())
        self.assertTrue(SessionStateStore(paths_b.process_state).exists())
        self.assertFalse(paths_b.enclave.is_file())
        self.assertIn(ActorId("codex:worker-a"), state_a.actors)
        self.assertNotIn(ActorId("codex:worker-a"), state_b.actors)
        with self.assertRaises(SessionNotFound):
            self.kernel.inspect(SessionId("missing-session"))

    def test_concurrent_actor_and_delegation_transactions_preserve_every_identity(self) -> None:
        """Root와 세 subagent 및 세 pending delegation이 concurrent transaction 뒤에도 모두 공존합니다."""
        session_id = "parallel-session"
        root_actor_id = "codex:root"
        actors = tuple(f"codex:worker-{number}" for number in range(3))
        delegations = tuple(f"delegation-{number}" for number in range(3))
        self.start_session(session_id, root_actor_id)
        context = multiprocessing.get_context("spawn")

        with ProcessPoolExecutor(max_workers=3, mp_context=context) as executor:
            actor_revisions = tuple(
                executor.map(
                    _start_actor,
                    (str(self.control_root),) * 3,
                    (session_id,) * 3,
                    actors,
                    (root_actor_id,) * 3,
                )
            )
        with ProcessPoolExecutor(max_workers=3, mp_context=context) as executor:
            delegation_revisions = tuple(
                executor.map(
                    _assign_delegation,
                    (str(self.control_root),) * 3,
                    (session_id,) * 3,
                    (root_actor_id,) * 3,
                    actors,
                    delegations,
                )
            )

        state = self.kernel.inspect(SessionId(session_id))

        self.assertEqual(3, len(actor_revisions))
        self.assertEqual(3, len(delegation_revisions))
        self.assertEqual(
            {ActorId(root_actor_id), *(ActorId(actor_id) for actor_id in actors)},
            set(state.actors),
        )
        self.assertEqual(
            {DelegationId(delegation_id) for delegation_id in delegations},
            set(state.delegations),
        )
        for delegation_id, target_actor_id in zip(delegations, actors, strict=True):
            delegation = state.delegations[DelegationId(delegation_id)]
            self.assertEqual(ActorId(root_actor_id), delegation.owner_actor_id)
            self.assertEqual(ActorId(target_actor_id), delegation.target_actor_id)

    def test_compare_and_transact_reports_one_conflict_without_lost_update(self) -> None:
        """같은 revision의 두 writer 중 하나만 commit되고 다른 writer는 typed conflict를 받습니다."""
        session_id = "cas-session"
        root_actor_id = "codex:root"
        self.start_session(session_id, root_actor_id)
        expected_revision = self.kernel.inspect(SessionId(session_id)).revision
        context = multiprocessing.get_context("spawn")

        with ProcessPoolExecutor(max_workers=2, mp_context=context) as executor:
            outcomes = tuple(
                executor.map(
                    _compare_and_start_actor,
                    (str(self.control_root),) * 2,
                    (session_id,) * 2,
                    ("codex:writer-a", "codex:writer-b"),
                    (root_actor_id,) * 2,
                    (expected_revision,) * 2,
                )
            )

        state = self.kernel.inspect(SessionId(session_id))
        committed_writers = {
            actor_id
            for actor_id in (ActorId("codex:writer-a"), ActorId("codex:writer-b"))
            if actor_id in state.actors
        }

        self.assertEqual(["committed", "conflict"], sorted(outcomes))
        self.assertEqual(1, len(committed_writers))
        self.assertEqual(expected_revision + 1, state.revision)

    def test_explicit_compare_rechecks_revision_before_returning_no_op_snapshot(self) -> None:
        """Idempotent candidate여도 explicit compare는 반환 직전 stale revision을 거부합니다."""
        session_id = SessionId("no-op-cas-session")
        root_actor_id = ActorId("codex:root")
        self.start_session(str(session_id), str(root_actor_id))
        state_path = self.locator.locate(session_id).process_state
        store = SessionStateStore(state_path)
        snapshot = store.read(session_id)
        idempotent_event = SessionStarted(
            session_id=session_id,
            resume_id=ResumeId(f"resume:{session_id}"),
            runtime=snapshot.session.runtime,
            root_actor_id=root_actor_id,
            idempotency_key="session-started:no-op-cas-session",
        )
        competing_actor_id = ActorId("codex:competing-writer")
        competing_event = ActorStarted(
            session_id=session_id,
            actor_id=competing_actor_id,
            parent_actor_id=root_actor_id,
            kind=ActorKind.SUBAGENT,
            idempotency_key="actor-started:competing-writer",
        )
        store._reducer = RevisionAdvancingReducer(
            SessionStateStore(state_path),
            competing_event,
        )

        with self.assertRaises(RevisionConflict):
            store.transact(idempotent_event, expected_revision=snapshot.revision)

        current = store.read(session_id)
        self.assertEqual(snapshot.revision + 1, current.revision)
        self.assertIn(competing_actor_id, current.actors)

    def test_pre_user_receipt_process_state_remains_backward_compatible(self) -> None:
        """새 receipt field 이전 foreground snapshot도 None authority로 안전하게 읽습니다."""
        session_id = SessionId("legacy-foreground-receipt-session")
        root_actor_id = ActorId("codex:root")
        self.start_session(str(session_id), str(root_actor_id))
        self.kernel.apply(
            ForegroundTurnProvisioned(
                session_id=session_id,
                actor_id=root_actor_id,
                idempotency_key="legacy-foreground-receipt:provision",
            )
        )
        self.kernel.apply(
            ForegroundTurnPrompted(
                session_id=session_id,
                actor_id=root_actor_id,
                vendor_turn_id="legacy-vendor-turn",
                idempotency_key="legacy-foreground-receipt:prompt",
            )
        )
        payload = self.kernel.inspect(session_id).to_payload()
        legacy_root = self.control_root / "legacy-import"
        legacy_root.mkdir()
        legacy_locator = SessionLocator(legacy_root)
        state_path = legacy_locator.locate(session_id).process_state
        state_path.parent.mkdir(parents=True)
        turns = payload["foreground_turns"]
        self.assertIsInstance(turns, dict)
        assert isinstance(turns, dict)
        legacy_turn = turns[str(root_actor_id)]
        self.assertIsInstance(legacy_turn, dict)
        assert isinstance(legacy_turn, dict)
        legacy_turn.pop("user_prompt_receipt")
        state_path.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
            encoding="utf-8",
        )

        reloaded = SessionKernel(legacy_locator).inspect(session_id)

        self.assertIsNone(reloaded.foreground_turns[root_actor_id].user_prompt_receipt)

    def test_provisional_turn_binds_prompt_without_changing_generation(self) -> None:
        """UserPromptSubmit provenance는 provisional generation에 한 번만 결합됩니다."""
        session_id = SessionId("provisional-prompt-session")
        actor_id = ActorId("codex:root")
        self.start_session(str(session_id), str(actor_id))
        provisional = self.kernel.apply(
            ForegroundTurnProvisioned(
                session_id=session_id,
                actor_id=actor_id,
                idempotency_key="provisional:start",
            )
        ).foreground_turns[actor_id]
        digest = "a" * 64
        event = ForegroundTurnPrompted(
            session_id=session_id,
            actor_id=actor_id,
            vendor_turn_id="vendor-turn-1",
            prompt_digest=digest,
            idempotency_key="provisional:prompt",
        )

        bound = self.kernel.apply(event).foreground_turns[actor_id]
        retried = self.kernel.apply(event).foreground_turns[actor_id]

        self.assertEqual(provisional.generation, bound.generation)
        self.assertEqual(provisional.revision + 1, bound.revision)
        self.assertEqual(bound.to_payload(), retried.to_payload())
        self.assertEqual("vendor-turn-1", bound.vendor_turn_id)
        self.assertIsNotNone(bound.user_prompt_receipt)
        assert bound.user_prompt_receipt is not None
        self.assertEqual(digest, bound.user_prompt_receipt.prompt_digest)

    def test_implicit_workflow_no_op_reduces_again_after_competing_commit(self) -> None:
        """Implicit idempotent retry도 final compare 뒤 최신 workflow에서 다시 판정합니다."""
        session_id = SessionId("implicit-workflow-no-op-session")
        root_actor_id = ActorId("codex:root")
        workflow_id = WorkflowId("workflow-no-op-cas")
        self.start_session(str(session_id), str(root_actor_id))
        self.kernel.apply(
            WorkflowStarted(
                session_id=session_id,
                workflow_id=workflow_id,
                owner_actor_id=root_actor_id,
                kind="test-workflow",
                goal=None,
                payload={"step": 0},
                idempotency_key="workflow-started:no-op-cas",
            )
        )
        already_applied = WorkflowAdvanced(
            session_id=session_id,
            workflow_id=workflow_id,
            actor_id=root_actor_id,
            expected_workflow_revision=0,
            payload={"step": 1},
            idempotency_key="workflow-advanced:no-op-cas:0",
        )
        self.kernel.apply(already_applied)
        competing_event = WorkflowAdvanced(
            session_id=session_id,
            workflow_id=workflow_id,
            actor_id=root_actor_id,
            expected_workflow_revision=1,
            payload={"step": 2},
            idempotency_key="workflow-advanced:no-op-cas:1",
        )
        state_path = self.locator.locate(session_id).process_state
        store = SessionStateStore(state_path)
        store._reducer = RevisionAdvancingReducer(
            SessionStateStore(state_path),
            competing_event,
        )

        with self.assertRaises(TransitionRejected):
            store.transact(already_applied)

        current = store.read(session_id)
        self.assertEqual(2, current.workflows[workflow_id].revision)
        self.assertEqual({"step": 2}, current.workflows[workflow_id].payload)

    def test_generic_workflow_events_cannot_mutate_reserved_adaptive_namespace(self) -> None:
        """Generic event와 malformed reserved event가 adaptive namespace를 만들지 못합니다."""
        session_id = SessionId("reserved-adaptive-session")
        root_actor_id = ActorId("codex:root")
        workflow_id = WorkflowId("reserved-adaptive-workflow")
        self.start_session(str(session_id), str(root_actor_id))

        with self.assertRaises(TransitionRejected):
            self.kernel.apply(
                WorkflowStarted(
                    session_id=session_id,
                    workflow_id=WorkflowId("forged-adaptive-start"),
                    owner_actor_id=root_actor_id,
                    kind="evaluate-harness",
                    goal=None,
                    payload={"skill_state": {"adaptive_control": {"forged": True}}},
                    idempotency_key="forged-adaptive:start",
                )
            )
        self.kernel.apply(
            WorkflowStarted(
                session_id=session_id,
                workflow_id=workflow_id,
                owner_actor_id=root_actor_id,
                kind="evaluate-harness",
                goal=None,
                payload={"skill_state": {}, "sibling": 0},
                idempotency_key="reserved-adaptive:start",
            )
        )
        with self.assertRaises(TransitionRejected):
            self.kernel.apply(
                WorkflowAdvanced(
                    session_id=session_id,
                    workflow_id=workflow_id,
                    actor_id=root_actor_id,
                    expected_workflow_revision=0,
                    payload={
                        "skill_state": {"adaptive_control": {"revision": 1}},
                        "sibling": 0,
                    },
                    idempotency_key="forged-adaptive:create",
                )
            )
        with self.assertRaises(TransitionRejected):
            self.kernel.apply(
                ReservedSkillStateAdvanced(
                    session_id,
                    workflow_id,
                    root_actor_id,
                    0,
                    {
                        "skill_state": {"adaptive_control": {"revision": 1}},
                        "sibling": 0,
                    },
                    "typed-adaptive:create",
                    reserved_namespaces=frozenset({"adaptive_control"}),
                )
            )
        current = self.kernel.inspect(session_id).workflows[workflow_id]
        self.assertEqual(0, current.revision)
        self.assertEqual({"skill_state": {}, "sibling": 0}, current.payload)

    def test_implicit_idempotent_transaction_preserves_snapshot_revision(self) -> None:
        """Expected revision이 없는 idempotent retry는 새 revision을 commit하지 않습니다."""
        session_id = SessionId("implicit-no-op-session")
        root_actor_id = ActorId("codex:root")
        self.start_session(str(session_id), str(root_actor_id))
        before = self.kernel.inspect(session_id)

        retried = self.kernel.apply(
            SessionStarted(
                session_id=session_id,
                resume_id=ResumeId(f"resume:{session_id}"),
                runtime=before.session.runtime,
                root_actor_id=root_actor_id,
                idempotency_key="session-started:implicit-no-op-session",
            )
        )

        self.assertEqual(before.revision, retried.revision)
        self.assertEqual(before.revision, self.kernel.inspect(session_id).revision)

    def test_process_death_before_commit_preserves_previous_canonical_state(self) -> None:
        """Commit 직전 process가 죽어도 SQLite에 이전의 유효 상태가 남습니다."""
        session_id = "crash-session"
        root_actor_id = "codex:root"
        self.start_session(session_id, root_actor_id)
        state_path = self.locator.locate(SessionId(session_id)).process_state
        canonical_before = self.kernel.inspect(SessionId(session_id)).to_payload()
        context = multiprocessing.get_context("spawn")
        process = context.Process(
            target=_crash_actor_commit,
            args=(
                str(state_path),
                session_id,
                "codex:crashing-writer",
                root_actor_id,
            ),
        )

        process.start()
        process.join(timeout=10)
        if process.is_alive():
            process.kill()
            process.join()
            self.fail("crash failpoint에 도달하지 못했습니다")

        canonical_after = self.kernel.inspect(SessionId(session_id)).to_payload()
        payload = canonical_after

        self.assertEqual(CRASH_EXIT_CODE, process.exitcode)
        self.assertEqual(canonical_before, canonical_after)
        self.assertNotIn("codex:crashing-writer", payload["actors"])

    def test_incident_events_preserve_typed_session_projection_and_lifecycle(self) -> None:
        """Incident는 session projection에서 typed event로 open 뒤 exact evidence와 함께 닫힙니다."""
        self.start_session("incident-session", "codex:root")
        session_id = SessionId("incident-session")
        occurrence_id = IncidentId("occurrence-1")
        actor_id = ActorId("codex:root")
        self.kernel.apply(
            HarnessIncidentRecorded(
                session_id=session_id,
                occurrence_id=occurrence_id,
                rule_id="monitor-loop-stopped",
                actor_id=actor_id,
                symptom="approval 전에 monitor loop가 중단됨",
                recorded_at="2026-08-04T00:00:00+00:00",
                idempotency_key="incident-recorded:occurrence-1",
            )
        )
        receipt = HarnessRegressionReceipt(
            command="uv run pytest scripts/agent_harness/tests -q",
            exit_code=0,
            head_sha="a" * 40,
            verified_at="2026-08-04T00:01:00+00:00",
            output_sha256="b" * 64,
        )
        self.kernel.apply(
            HarnessIncidentResolved(
                session_id=session_id,
                occurrence_id=occurrence_id,
                actor_id=actor_id,
                root_cause="terminal delivery 소비 여부를 확인하지 않음",
                harness_fix=("scripts/agent_harness/checker.py",),
                regression_evidence=(receipt,),
                resolved_at="2026-08-04T00:02:00+00:00",
                idempotency_key="incident-resolved:occurrence-1",
            )
        )

        state = self.kernel.inspect(session_id)
        incident = state.incidents[occurrence_id]

        self.assertEqual(HarnessIncidentStatus.RESOLVED, incident.status)
        self.assertEqual(actor_id, incident.actor_id)
        self.assertEqual("monitor-loop-stopped", incident.rule_id)
        self.assertEqual((receipt,), incident.regression_evidence)
        self.assertEqual("resolved", incident.to_payload()["status"])

    def test_incident_record_rejects_second_open_occurrence_for_same_rule(self) -> None:
        """같은 stable rule의 open occurrence는 optimistic retry 뒤에도 하나만 존재합니다."""
        self.start_session("incident-session", "codex:root")
        session_id = SessionId("incident-session")
        actor_id = ActorId("codex:root")
        for occurrence_id in ("occurrence-1", "occurrence-2"):
            event = HarnessIncidentRecorded(
                session_id=session_id,
                occurrence_id=IncidentId(occurrence_id),
                rule_id="same-rule",
                actor_id=actor_id,
                symptom="같은 결함",
                recorded_at="2026-08-04T00:00:00+00:00",
                idempotency_key=f"incident-recorded:{occurrence_id}",
            )
            if occurrence_id == "occurrence-1":
                self.kernel.apply(event)
            else:
                with self.assertRaisesRegex(TransitionRejected, "open incident already exists"):
                    self.kernel.apply(event)


if __name__ == "__main__":  # pragma: no cover - test entrypoint
    import unittest

    unittest.main()

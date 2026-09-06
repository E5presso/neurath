"""Material action batch의 domain과 SessionKernel persistence 계약을 검증합니다."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from scripts.agent_harness.adaptive_control import (
    CriterionSpec,
    EvidenceKind,
    GapInventory,
    GoalContract,
    OracleOwner,
    RequirementSection,
    approved_requirement_fingerprint,
)
from scripts.agent_harness.adaptive_control_store import AdaptiveControlState
from scripts.agent_harness.material_action import (
    AdaptiveActionBinding,
    MaterialActionBatch,
    MaterialActionKind,
    MaterialActionResolution,
    MaterialActionStatus,
    ObservableDeltaKind,
    ObservableExpectation,
    ObservableObservation,
    ToolReceipt,
    ToolReceiptOutcome,
    material_observable_digest,
)
from scripts.agent_harness.session_kernel import (
    ActorId,
    EffectId,
    EffectKind,
    ForegroundTurnPrompted,
    ForegroundTurnProvisioned,
    MaterialActionPrepared,
    MaterialActionResolved,
    MaterialActionToolObserved,
    MaterialActionToolStarted,
    OutboxEffect,
    ReservedSkillStateAdvanced,
    ResumeId,
    RevisionConflict,
    SessionId,
    SessionKernel,
    SessionLocator,
    SessionResumed,
    SessionRuntime,
    SessionStarted,
    TransitionRejected,
    WorkflowAdvanced,
    WorkflowId,
    WorkflowStarted,
)
from scripts.agent_harness.state_handle import (
    RuntimeEnvironmentResolver,
    StateHandle,
    StateHandleAuthorityError,
)


def _digest(value: str) -> str:
    """Fixture text를 canonical SHA-256으로 바꿉니다."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class MaterialActionDomainTest(TestCase):
    """Raw command/output 없이 bounded batch state가 전이되는지 검증합니다."""

    def test_symlink_target_identity_is_observable_without_following_the_target(self) -> None:
        """Graph-link mutation은 link text 자체를 digest하며 target directory를 읽지 않습니다."""
        with TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first"
            second = root / "second"
            first.mkdir()
            second.mkdir()
            link = root / "graphify-out"
            link.symlink_to(first, target_is_directory=True)
            before = material_observable_digest(link)

            link.unlink()
            link.symlink_to(second, target_is_directory=True)
            after = material_observable_digest(link)

        self.assertIsNotNone(before)
        self.assertIsNotNone(after)
        self.assertNotEqual(before, after)

    def _batch(self) -> MaterialActionBatch:
        return MaterialActionBatch.prepare(
            batch_id="batch-1",
            sequence=1,
            session_id="session-a",
            actor_id="codex:root",
            turn_generation=1,
            turn_revision=0,
            kind=MaterialActionKind.LOCAL_MUTATION,
            targets=("/repo/a.py", "/repo/b.py"),
            expectations=(
                ObservableExpectation(
                    observable_id="/repo/a.py",
                    baseline_digest=_digest("before"),
                    expected_delta=ObservableDeltaKind.CHANGED,
                    expected_digest=None,
                ),
            ),
            adaptive_binding=None,
        )

    def test_batch_supports_multiple_sequential_tool_receipts_without_raw_payloads(self) -> None:
        """한 batch는 invocation 하나씩 시작/관찰하고 digest와 delta만 직렬화합니다."""
        batch = self._batch()
        first = batch.start_tool(
            invocation_id="tool-1",
            tool_name="apply_patch",
            request_digest=_digest("normalized request 1"),
            targets=("/repo/a.py",),
        )

        with self.assertRaises(ValueError):
            first.start_tool(
                invocation_id="tool-2",
                tool_name="exec_command",
                request_digest=_digest("normalized request 2"),
                targets=("/repo/b.py",),
            )

        observed = first.observe_tool(
            "tool-1",
            ToolReceipt(
                receipt_id="post-tool:tool-1",
                request_digest=_digest("normalized request 1"),
                outcome=ToolReceiptOutcome.SUCCEEDED,
                output_digest=_digest("bounded runtime output"),
                observations=(
                    ObservableObservation(
                        observable_id="/repo/a.py",
                        current_digest=_digest("after"),
                    ),
                ),
            ),
        )
        second = observed.start_tool(
            invocation_id="tool-2",
            tool_name="exec_command",
            request_digest=_digest("normalized request 2"),
            targets=("/repo/b.py",),
        )

        payload = second.to_payload()
        encoded = json.dumps(payload, sort_keys=True)
        self.assertEqual(2, len(second.invocations))
        self.assertNotIn("normalized request", encoded)
        self.assertNotIn("bounded runtime output", encoded)
        self.assertNotIn("raw_command", encoded)
        self.assertNotIn("raw_output", encoded)
        self.assertNotIn("actual_delta", encoded)

    def test_duplicate_start_and_observation_are_idempotent_but_conflicts_fail_closed(self) -> None:
        """Runtime retry는 같은 digest/receipt만 no-op이고 같은 identity의 다른 내용은 거부합니다."""
        started = self._batch().start_tool(
            invocation_id="tool-1",
            tool_name="apply_patch",
            request_digest=_digest("request"),
            targets=("/repo/a.py",),
        )

        duplicate_start = started.start_tool(
            invocation_id="tool-1",
            tool_name="apply_patch",
            request_digest=_digest("request"),
            targets=("/repo/a.py",),
        )
        self.assertIs(started, duplicate_start)
        with self.assertRaises(ValueError):
            started.start_tool(
                invocation_id="tool-1",
                tool_name="apply_patch",
                request_digest=_digest("different request"),
                targets=("/repo/a.py",),
            )

        receipt = ToolReceipt(
            receipt_id="post-tool:tool-1",
            request_digest=_digest("request"),
            outcome=ToolReceiptOutcome.FAILED,
            output_digest=_digest("failure"),
            observations=(
                ObservableObservation(
                    observable_id="/repo/a.py",
                    current_digest=_digest("same"),
                ),
            ),
        )
        observed = started.observe_tool("tool-1", receipt)
        self.assertIs(observed, observed.observe_tool("tool-1", receipt))
        with self.assertRaises(ValueError):
            observed.observe_tool(
                "tool-1",
                ToolReceipt(
                    receipt_id="post-tool:tool-1",
                    request_digest=_digest("request"),
                    outcome=ToolReceiptOutcome.SUCCEEDED,
                    output_digest=_digest("different output"),
                    observations=receipt.observations,
                ),
            )

    def test_tool_receipt_round_trip_preserves_optional_duration_without_defaulting_to_zero(
        self,
    ) -> None:
        """Runtime duration은 current 정수만 보존하고 legacy 누락은 None으로 복원합니다."""
        receipt = ToolReceipt(
            receipt_id="post-tool:duration",
            request_digest=_digest("request"),
            outcome=ToolReceiptOutcome.SUCCEEDED,
            output_digest=_digest("output"),
            observations=(),
            duration_milliseconds=37,
        )

        restored = ToolReceipt.from_payload(receipt.to_payload())
        legacy = dict(receipt.to_payload())
        legacy.pop("duration_milliseconds")

        self.assertEqual(37, restored.duration_milliseconds)
        self.assertIsNone(ToolReceipt.from_payload(legacy).duration_milliseconds)
        with self.assertRaises(ValueError):
            ToolReceipt(
                receipt_id="post-tool:invalid-duration",
                request_digest=_digest("request"),
                outcome=ToolReceiptOutcome.SUCCEEDED,
                output_digest=_digest("output"),
                observations=(),
                duration_milliseconds=-1,
            )

    def test_started_target_must_be_within_the_prepared_exact_boundary(self) -> None:
        """Prepared batch 밖 normalized target으로 mutation scope를 넓힐 수 없습니다."""
        with self.assertRaises(ValueError):
            self._batch().start_tool(
                invocation_id="tool-1",
                tool_name="apply_patch",
                request_digest=_digest("request"),
                targets=("/repo/not-authorized.py",),
            )
        with self.assertRaises(ValueError):
            MaterialActionBatch.prepare(
                batch_id="relative-local-target",
                sequence=1,
                session_id="session-a",
                actor_id="codex:root",
                turn_generation=1,
                turn_revision=0,
                kind=MaterialActionKind.LOCAL_MUTATION,
                targets=("relative.py",),
                expectations=(
                    ObservableExpectation(
                        observable_id="relative.py",
                        baseline_digest=None,
                        expected_delta=ObservableDeltaKind.CREATED,
                        expected_digest=None,
                    ),
                ),
                adaptive_binding=None,
            )

    def test_completed_resolution_requires_successful_receipts_and_matching_latest_deltas(
        self,
    ) -> None:
        """Failed, missing, unavailable, kind/digest mismatch는 completed self-attestation이 아닙니다."""
        expected_digest = _digest("expected final")
        batch = MaterialActionBatch.prepare(
            batch_id="batch-completion",
            sequence=1,
            session_id="session-a",
            actor_id="codex:root",
            turn_generation=1,
            turn_revision=0,
            kind=MaterialActionKind.LOCAL_MUTATION,
            targets=("/repo/a.py", "/repo/test_a.py"),
            expectations=(
                ObservableExpectation(
                    observable_id="/repo/a.py",
                    baseline_digest=_digest("before"),
                    expected_delta=ObservableDeltaKind.CHANGED,
                    expected_digest=expected_digest,
                ),
                ObservableExpectation(
                    observable_id="/repo/test_a.py",
                    baseline_digest=_digest("same"),
                    expected_delta=ObservableDeltaKind.UNCHANGED,
                    expected_digest=None,
                ),
            ),
            adaptive_binding=None,
        ).start_tool(
            invocation_id="tool-1",
            tool_name="apply_patch",
            request_digest=_digest("request-1"),
            targets=("/repo/a.py",),
        )
        failed = batch.observe_tool(
            "tool-1",
            ToolReceipt(
                receipt_id="post-tool:tool-1",
                request_digest=_digest("request-1"),
                outcome=ToolReceiptOutcome.FAILED,
                output_digest=_digest("failed"),
                observations=(),
            ),
        )

        with self.assertRaises(ValueError):
            failed.resolve(MaterialActionResolution.COMPLETED)
        self.assertEqual(
            MaterialActionResolution.ABORTED,
            failed.resolve(MaterialActionResolution.ABORTED).resolution,
        )

        recovered = failed.start_tool(
            invocation_id="tool-2",
            tool_name="exec_command",
            request_digest=_digest("request-2"),
            targets=("/repo/a.py",),
        ).observe_tool(
            "tool-2",
            ToolReceipt(
                receipt_id="post-tool:tool-2",
                request_digest=_digest("request-2"),
                outcome=ToolReceiptOutcome.SUCCEEDED,
                output_digest=_digest("passed"),
                observations=(
                    ObservableObservation(
                        observable_id="/repo/a.py",
                        current_digest=expected_digest,
                    ),
                    ObservableObservation(
                        observable_id="/repo/test_a.py",
                        current_digest=_digest("same"),
                    ),
                ),
            ),
        )
        assessment = recovered.delta_assessment

        self.assertFalse(assessment.is_complete)
        self.assertEqual(("tool-1",), assessment.unsuccessful_invocation_ids)
        with self.assertRaises(ValueError):
            recovered.resolve(MaterialActionResolution.COMPLETED)

        clean = (
            self
            ._batch()
            .start_tool(
                invocation_id="tool-clean",
                tool_name="apply_patch",
                request_digest=_digest("clean request"),
                targets=("/repo/a.py",),
            )
            .observe_tool(
                "tool-clean",
                ToolReceipt(
                    receipt_id="post-tool:clean",
                    request_digest=_digest("clean request"),
                    outcome=ToolReceiptOutcome.SUCCEEDED,
                    output_digest=_digest("clean result"),
                    observations=(
                        ObservableObservation(
                            observable_id="/repo/a.py",
                            current_digest=_digest("after"),
                        ),
                    ),
                ),
            )
        )
        self.assertTrue(clean.delta_assessment.is_complete)
        self.assertEqual(
            ObservableDeltaKind.CHANGED,
            clean.delta_assessment.effective_deltas[0].actual_delta,
        )
        self.assertEqual(
            MaterialActionResolution.COMPLETED,
            clean.resolve(MaterialActionResolution.COMPLETED).resolution,
        )

    def test_prepared_but_unstarted_batch_can_abort_or_block_without_forging_receipt(
        self,
    ) -> None:
        """실행하지 않은 intent는 receipt 없이 중단할 수 있지만 완료로 위조할 수 없습니다."""
        aborted = self._batch().resolve(MaterialActionResolution.ABORTED)
        blocked = self._batch().resolve(MaterialActionResolution.BLOCKED)

        self.assertEqual(MaterialActionResolution.ABORTED, aborted.resolution)
        self.assertEqual(MaterialActionResolution.BLOCKED, blocked.resolution)
        self.assertEqual((), aborted.invocations)
        self.assertEqual((), blocked.invocations)
        with self.assertRaises(ValueError):
            self._batch().resolve(MaterialActionResolution.COMPLETED)


class MaterialActionKernelTest(TestCase):
    """Actor/current foreground turn에 결속된 canonical projection을 검증합니다."""

    def setUp(self) -> None:
        """Exact actor foreground turn이 열린 isolated kernel fixture를 준비합니다."""
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.locator = SessionLocator(Path(self.temporary_directory.name))
        self.kernel = SessionKernel(self.locator)
        self.session_id = SessionId("session-a")
        self.actor_id = ActorId("codex:root")
        self.kernel.apply(
            SessionStarted(
                session_id=self.session_id,
                resume_id=ResumeId("resume-a"),
                runtime=SessionRuntime.CODEX,
                root_actor_id=self.actor_id,
                idempotency_key="session:start",
            )
        )
        self.kernel.apply(
            ForegroundTurnProvisioned(
                session_id=self.session_id,
                actor_id=self.actor_id,
                idempotency_key="turn:provision",
            )
        )
        self.kernel.apply(
            ForegroundTurnPrompted(
                session_id=self.session_id,
                actor_id=self.actor_id,
                vendor_turn_id="vendor-turn-1",
                idempotency_key="turn:prompt",
            )
        )

    def _prepare(self, *, batch_id: str = "batch-1", sequence: int = 1) -> MaterialActionPrepared:
        return MaterialActionPrepared(
            session_id=self.session_id,
            actor_id=self.actor_id,
            batch_id=batch_id,
            sequence=sequence,
            expected_turn_generation=1,
            expected_turn_revision=1,
            kind=MaterialActionKind.LOCAL_MUTATION,
            targets=("/repo/a.py",),
            expectations=(
                ObservableExpectation(
                    observable_id="/repo/a.py",
                    baseline_digest=_digest("before"),
                    expected_delta=ObservableDeltaKind.CHANGED,
                    expected_digest=None,
                ),
            ),
            adaptive_binding=None,
            idempotency_key=f"action:prepare:{batch_id}",
        )

    def _start(self, revision: int, *, batch_id: str = "batch-1") -> MaterialActionToolStarted:
        return MaterialActionToolStarted(
            session_id=self.session_id,
            actor_id=self.actor_id,
            batch_id=batch_id,
            expected_batch_revision=revision,
            invocation_id="tool-1",
            tool_name="apply_patch",
            request_digest=_digest("request"),
            targets=("/repo/a.py",),
            idempotency_key=f"action:start:{batch_id}:tool-1",
        )

    def _receipt(self) -> ToolReceipt:
        return ToolReceipt(
            receipt_id="post-tool:tool-1",
            request_digest=_digest("request"),
            outcome=ToolReceiptOutcome.SUCCEEDED,
            output_digest=_digest("output"),
            observations=(
                ObservableObservation(
                    observable_id="/repo/a.py",
                    current_digest=_digest("after"),
                ),
            ),
        )

    def _adaptive_contract(self, suffix: str, intent_revision: int) -> GoalContract:
        """Semantic batch fixture용 current goal contract를 만듭니다."""
        goal = f"{suffix} 목표를 완수한다"
        constraints = ("현재 adaptive authority에 결속한다",)
        non_goals = ("stale authority를 재사용하지 않는다",)
        source_revision = f"source:{intent_revision}"
        requirement_id = f"REQ-{suffix}"
        return GoalContract(
            goal=goal,
            constraints=constraints,
            requirement_ids=frozenset({requirement_id}),
            criteria=(
                CriterionSpec(
                    criterion_id=f"{suffix}-behavior",
                    description="Semantic action이 current authority만 사용한다",
                    source_requirement_id=requirement_id,
                    approved_requirement_fingerprint=approved_requirement_fingerprint(
                        goal,
                        constraints,
                        non_goals,
                        intent_revision,
                        source_revision,
                    ),
                    observer="test runner",
                    precondition="Adaptive workflow가 active 상태다",
                    stimulus="Material action lifecycle을 진행한다",
                    expected_outcome="Stale binding이 거부된다",
                    oracle_owner=OracleOwner.EXECUTABLE,
                    hard=True,
                    required_evidence=frozenset({EvidenceKind.PROPERTY_TEST}),
                ),
            ),
            non_goals=non_goals,
            intent_revision=intent_revision,
            source_revision=source_revision,
        )

    def _adaptive_state(self, suffix: str, intent_revision: int) -> AdaptiveControlState:
        """완전히 평가된 gap inventory와 goal contract를 하나의 snapshot으로 묶습니다."""
        contract = self._adaptive_contract(suffix, intent_revision)
        return AdaptiveControlState.empty(
            contract,
            GapInventory(
                intent_revision=intent_revision,
                source_revision=f"repository:{intent_revision}",
                assessed_sections=frozenset(RequirementSection),
                gaps=(),
            ),
        )

    def _semantic_fixture(
        self,
        suffix: str,
    ) -> tuple[SessionKernel, SessionId, ActorId, WorkflowId, GoalContract]:
        """독립 session에 adaptive workflow와 semantic material batch를 준비합니다."""
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        kernel = SessionKernel(SessionLocator(Path(directory.name)))
        session_id = SessionId(f"semantic-{suffix}")
        actor_id = ActorId(f"codex:{suffix}")
        workflow_id = WorkflowId(f"workflow-{suffix}")
        adaptive = self._adaptive_state(f"{suffix}-initial", 1)
        kernel.apply(
            SessionStarted(
                session_id=session_id,
                resume_id=ResumeId(f"resume-{suffix}"),
                runtime=SessionRuntime.CODEX,
                root_actor_id=actor_id,
                idempotency_key="session:start",
            )
        )
        kernel.apply(
            ForegroundTurnProvisioned(
                session_id=session_id,
                actor_id=actor_id,
                idempotency_key="turn:provision",
            )
        )
        kernel.apply(
            ForegroundTurnPrompted(
                session_id=session_id,
                actor_id=actor_id,
                vendor_turn_id=f"vendor-{suffix}",
                idempotency_key="turn:prompt",
            )
        )
        kernel.apply(
            WorkflowStarted(
                session_id=session_id,
                workflow_id=workflow_id,
                owner_actor_id=actor_id,
                kind="evaluate-harness",
                goal=adaptive.contract.goal,
                payload={"skill_state": {}, "marker": 0},
                idempotency_key="workflow:start",
            )
        )
        kernel.apply(
            ReservedSkillStateAdvanced(
                session_id,
                workflow_id,
                actor_id,
                0,
                {
                    "skill_state": {"adaptive_control": adaptive.to_payload()},
                    "marker": 0,
                },
                "workflow:initialize-adaptive",
                reserved_namespaces=frozenset({"adaptive_control"}),
            )
        )
        kernel.apply(
            MaterialActionPrepared(
                session_id=session_id,
                actor_id=actor_id,
                batch_id=f"batch-{suffix}",
                sequence=1,
                expected_turn_generation=1,
                expected_turn_revision=1,
                kind=MaterialActionKind.SEMANTIC_DECISION,
                targets=("decision:architecture",),
                expectations=(
                    ObservableExpectation(
                        observable_id="decision:architecture",
                        baseline_digest=None,
                        expected_delta=ObservableDeltaKind.CREATED,
                        expected_digest=None,
                    ),
                ),
                adaptive_binding=AdaptiveActionBinding(
                    workflow_id=str(workflow_id),
                    workflow_revision=1,
                    goal_fingerprint=adaptive.contract.fingerprint,
                ),
                idempotency_key="action:prepare",
            )
        )
        return kernel, session_id, actor_id, workflow_id, adaptive.contract

    def _advance_adaptive_workflow(
        self,
        kernel: SessionKernel,
        session_id: SessionId,
        actor_id: ActorId,
        workflow_id: WorkflowId,
    ) -> int:
        """Adaptive payload를 보존한 채 prepared binding 뒤 workflow revision을 갱신합니다."""
        current = kernel.inspect(session_id).workflows[workflow_id]
        skill_state = current.payload["skill_state"]
        assert isinstance(skill_state, dict)
        kernel.apply(
            WorkflowAdvanced(
                session_id,
                workflow_id,
                actor_id,
                1,
                {"skill_state": skill_state, "marker": 1},
                "workflow:advance",
            )
        )
        return kernel.inspect(session_id).workflows[workflow_id].revision

    def _semantic_receipt(self) -> ToolReceipt:
        """Semantic expectation을 충족하는 raw-free receipt를 만듭니다."""
        return ToolReceipt(
            receipt_id="post-tool:tool-1",
            request_digest=_digest("semantic request"),
            outcome=ToolReceiptOutcome.SUCCEEDED,
            output_digest=_digest("semantic output"),
            observations=(
                ObservableObservation(
                    observable_id="decision:architecture",
                    current_digest=_digest("accepted decision"),
                ),
            ),
        )

    def test_no_skill_foreground_turn_persists_one_batch_and_multiple_invocations(self) -> None:
        """Workflow가 전혀 없어도 actor turn에 batch를 준비하고 PostTool receipt를 누적합니다."""
        prepared = self.kernel.apply(self._prepare())
        batch = prepared.material_actions[self.actor_id]
        self.assertEqual({}, prepared.workflows)
        self.assertIsNone(batch.adaptive_binding)

        started = self.kernel.apply(self._start(batch.revision))
        started_batch = started.material_actions[self.actor_id]
        observed = self.kernel.apply(
            MaterialActionToolObserved(
                session_id=self.session_id,
                actor_id=self.actor_id,
                batch_id="batch-1",
                expected_batch_revision=started_batch.revision,
                invocation_id="tool-1",
                receipt=self._receipt(),
                idempotency_key="action:observe:batch-1:tool-1",
            )
        )

        reloaded = self.kernel.inspect(self.session_id)
        self.assertEqual(
            observed.material_actions[self.actor_id].to_payload(),
            reloaded.material_actions[self.actor_id].to_payload(),
        )
        receipt = reloaded.material_actions[self.actor_id].invocations[0].receipt
        self.assertIsNotNone(receipt)
        assert receipt is not None
        self.assertEqual(ToolReceiptOutcome.SUCCEEDED, receipt.outcome)

    def test_prepare_requires_exact_current_turn_and_new_batch_waits_for_resolution(self) -> None:
        """Stale turn과 concurrent open batch는 거부되고 resolved sequence 다음 batch만 열립니다."""
        with self.assertRaises(TransitionRejected):
            self.kernel.apply(
                MaterialActionPrepared(
                    session_id=self.session_id,
                    actor_id=self.actor_id,
                    batch_id="stale",
                    sequence=1,
                    expected_turn_generation=1,
                    expected_turn_revision=99,
                    kind=MaterialActionKind.LOCAL_MUTATION,
                    targets=("/repo/a.py",),
                    expectations=self._prepare().expectations,
                    adaptive_binding=None,
                    idempotency_key="action:prepare:stale",
                )
            )

        prepared = self.kernel.apply(self._prepare())
        with self.assertRaises(TransitionRejected):
            self.kernel.apply(self._prepare(batch_id="batch-2", sequence=2))

        batch = prepared.material_actions[self.actor_id]
        started = self.kernel.apply(self._start(batch.revision))
        batch = started.material_actions[self.actor_id]
        observed = self.kernel.apply(
            MaterialActionToolObserved(
                session_id=self.session_id,
                actor_id=self.actor_id,
                batch_id=batch.batch_id,
                expected_batch_revision=batch.revision,
                invocation_id="tool-1",
                receipt=self._receipt(),
                idempotency_key="action:observe:batch-1:tool-1",
            )
        )
        batch = observed.material_actions[self.actor_id]
        resolved = self.kernel.apply(
            MaterialActionResolved(
                session_id=self.session_id,
                actor_id=self.actor_id,
                batch_id=batch.batch_id,
                expected_batch_revision=batch.revision,
                resolution=MaterialActionResolution.COMPLETED,
                idempotency_key="action:resolve:batch-1",
            )
        )

        with self.assertRaises(TransitionRejected):
            self.kernel.apply(self._prepare(batch_id="skipped-batch", sequence=4))

        next_state = self.kernel.apply(self._prepare(batch_id="batch-2", sequence=2))
        self.assertEqual(2, next_state.material_actions[self.actor_id].sequence)
        self.assertGreater(next_state.revision, resolved.revision)

    def test_explicit_session_cas_and_duplicate_runtime_delivery_are_stable(self) -> None:
        """Stale session writer는 거부되고 exact duplicate start/receipt는 revision을 올리지 않습니다."""
        before = self.kernel.inspect(self.session_id)
        prepared = self.kernel.apply(self._prepare(), expected_revision=before.revision)
        with self.assertRaises(RevisionConflict):
            self.kernel.apply(
                self._start(prepared.material_actions[self.actor_id].revision),
                expected_revision=before.revision,
            )

        started = self.kernel.apply(
            self._start(prepared.material_actions[self.actor_id].revision),
            expected_revision=prepared.revision,
        )
        duplicate = self.kernel.apply(
            self._start(prepared.material_actions[self.actor_id].revision)
        )
        self.assertEqual(started.revision, duplicate.revision)

        batch = started.material_actions[self.actor_id]
        observe = MaterialActionToolObserved(
            session_id=self.session_id,
            actor_id=self.actor_id,
            batch_id=batch.batch_id,
            expected_batch_revision=batch.revision,
            invocation_id="tool-1",
            receipt=self._receipt(),
            idempotency_key="action:observe:batch-1:tool-1",
        )
        observed = self.kernel.apply(observe)
        duplicate_observed = self.kernel.apply(observe)
        self.assertEqual(observed.revision, duplicate_observed.revision)

    def test_process_state_without_material_actions_decodes_as_empty_projection(self) -> None:
        """Action projection 이전 snapshot은 schema bump 없이 empty default로 읽힙니다."""
        state_path = self.locator.locate(self.session_id).process_state
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        payload.pop("material_actions", None)
        state_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")

        reloaded = self.kernel.inspect(self.session_id)

        self.assertEqual({}, reloaded.material_actions)

    def test_adaptive_binding_is_optional_but_never_partially_constructed(self) -> None:
        """No-skill local path는 None이지만 semantic decision은 완전한 adaptive authority를 요구합니다."""
        with self.assertRaises(ValueError):
            AdaptiveActionBinding(
                workflow_id="workflow-a",
                workflow_revision=-1,
                goal_fingerprint=_digest("goal"),
            )
        with self.assertRaises(ValueError):
            MaterialActionBatch.prepare(
                batch_id="semantic-without-authority",
                sequence=1,
                session_id="session-a",
                actor_id="codex:root",
                turn_generation=1,
                turn_revision=0,
                kind=MaterialActionKind.SEMANTIC_DECISION,
                targets=("decision:architecture",),
                expectations=(
                    ObservableExpectation(
                        observable_id="decision:architecture",
                        baseline_digest=None,
                        expected_delta=ObservableDeltaKind.CREATED,
                        expected_digest=None,
                    ),
                ),
                adaptive_binding=None,
            )

    def test_semantic_batch_rejects_tool_start_observe_and_completion_after_adaptive_revision_or_goal_changes(
        self,
    ) -> None:
        """Semantic lifecycle의 모든 mutation은 prepared authority를 current state와 재검증합니다."""
        for stage in ("start", "observe", "resolve"):
            with self.subTest(stage=stage):
                kernel, session_id, actor_id, workflow_id, original = self._semantic_fixture(stage)
                batch = kernel.inspect(session_id).material_actions[actor_id]
                if stage in {"observe", "resolve"}:
                    state = kernel.apply(
                        MaterialActionToolStarted(
                            session_id=session_id,
                            actor_id=actor_id,
                            batch_id=batch.batch_id,
                            expected_batch_revision=batch.revision,
                            invocation_id="tool-1",
                            tool_name="apply_patch",
                            request_digest=_digest("semantic request"),
                            targets=("decision:architecture",),
                            idempotency_key="action:start",
                        )
                    )
                    batch = state.material_actions[actor_id]
                if stage == "resolve":
                    state = kernel.apply(
                        MaterialActionToolObserved(
                            session_id=session_id,
                            actor_id=actor_id,
                            batch_id=batch.batch_id,
                            expected_batch_revision=batch.revision,
                            invocation_id="tool-1",
                            receipt=self._semantic_receipt(),
                            idempotency_key="action:observe",
                        )
                    )
                    batch = state.material_actions[actor_id]
                changed_revision = self._advance_adaptive_workflow(
                    kernel,
                    session_id,
                    actor_id,
                    workflow_id,
                )
                binding = batch.adaptive_binding
                self.assertIsNotNone(binding)
                assert binding is not None
                self.assertEqual(original.fingerprint, binding.goal_fingerprint)
                self.assertGreater(changed_revision, binding.workflow_revision)
                with self.assertRaises(TransitionRejected):
                    if stage == "start":
                        kernel.apply(
                            MaterialActionToolStarted(
                                session_id=session_id,
                                actor_id=actor_id,
                                batch_id=batch.batch_id,
                                expected_batch_revision=batch.revision,
                                invocation_id="tool-1",
                                tool_name="apply_patch",
                                request_digest=_digest("semantic request"),
                                targets=("decision:architecture",),
                                idempotency_key="action:start",
                            )
                        )
                    elif stage == "observe":
                        kernel.apply(
                            MaterialActionToolObserved(
                                session_id=session_id,
                                actor_id=actor_id,
                                batch_id=batch.batch_id,
                                expected_batch_revision=batch.revision,
                                invocation_id="tool-1",
                                receipt=self._semantic_receipt(),
                                idempotency_key="action:observe",
                            )
                        )
                    else:
                        kernel.apply(
                            MaterialActionResolved(
                                session_id=session_id,
                                actor_id=actor_id,
                                batch_id=batch.batch_id,
                                expected_batch_revision=batch.revision,
                                resolution=MaterialActionResolution.COMPLETED,
                                idempotency_key="action:resolve",
                            )
                        )

    def test_resume_can_terminalize_orphaned_inflight_without_forging_success(self) -> None:
        """Exact resume만 orphaned PreTool을 UNKNOWN/BLOCKED로 닫고 live 취소는 거부합니다."""
        prepared = self.kernel.apply(self._prepare())
        batch = prepared.material_actions[self.actor_id]
        started = self.kernel.apply(self._start(batch.revision))
        batch = started.material_actions[self.actor_id]

        with self.assertRaises(TransitionRejected):
            self.kernel.apply(
                MaterialActionResolved(
                    session_id=self.session_id,
                    actor_id=self.actor_id,
                    batch_id=batch.batch_id,
                    expected_batch_revision=batch.revision,
                    resolution=MaterialActionResolution.BLOCKED,
                    idempotency_key="action:live-cancel",
                )
            )

        resumed = self.kernel.apply(
            SessionResumed(
                session_id=self.session_id,
                actor_id=self.actor_id,
                resume_id=ResumeId("resume-after-runtime-interruption"),
                lifecycle_provenance_id="vendor-resume-after-crash",
                idempotency_key="session:resume-after-crash",
                effect=OutboxEffect(
                    effect_id=EffectId("effect:resume-after-crash"),
                    actor_id=self.actor_id,
                    kind=EffectKind.CONTEXT_INJECTION,
                    delivery_key="delivery:resume-after-crash",
                    payload={"cause": "runtime-resumed"},
                ),
            )
        )

        recovered = resumed.material_actions[self.actor_id]
        self.assertIs(MaterialActionStatus.RESOLVED, recovered.status)
        self.assertIs(MaterialActionResolution.BLOCKED, recovered.resolution)
        self.assertIsNone(recovered.in_flight)
        receipt = recovered.invocations[0].receipt
        self.assertIsNotNone(receipt)
        assert receipt is not None
        self.assertIs(ToolReceiptOutcome.UNKNOWN, receipt.outcome)
        self.assertEqual((), receipt.observations)


class MaterialActionStateHandleTest(TestCase):
    """Runtime-bound handle이 material-action event의 actor/session replay를 차단합니다."""

    def test_handle_rejects_cross_actor_and_cross_session_prepare(self) -> None:
        """Prepared intent는 exact runtime session과 current actor 밖으로 replay되지 않습니다."""
        temporary_directory = TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        locator = SessionLocator(Path(temporary_directory.name))
        binding = RuntimeEnvironmentResolver().resolve({"CODEX_THREAD_ID": "thread-a"})
        handle = StateHandle.initialize(locator, binding)
        handle.apply(
            ForegroundTurnProvisioned(
                session_id=binding.session_id,
                actor_id=binding.actor_id,
                idempotency_key="turn:provision",
            )
        )
        handle.apply(
            ForegroundTurnPrompted(
                session_id=binding.session_id,
                actor_id=binding.actor_id,
                vendor_turn_id="vendor-turn-a",
                idempotency_key="turn:prompt",
            )
        )

        def event(
            session_id: SessionId,
            actor_id: ActorId,
            kind: MaterialActionKind = MaterialActionKind.LOCAL_MUTATION,
        ) -> MaterialActionPrepared:
            """Authority replay case마다 동일 prepared intent event를 생성합니다."""
            return MaterialActionPrepared(
                session_id=session_id,
                actor_id=actor_id,
                batch_id="batch-1",
                sequence=1,
                expected_turn_generation=1,
                expected_turn_revision=1,
                kind=kind,
                targets=("/repo/a.py",),
                expectations=(
                    ObservableExpectation(
                        observable_id="/repo/a.py",
                        baseline_digest=_digest("before"),
                        expected_delta=ObservableDeltaKind.CHANGED,
                        expected_digest=None,
                    ),
                ),
                adaptive_binding=None,
                idempotency_key="action:prepare",
            )

        with self.assertRaises(StateHandleAuthorityError):
            handle.apply(event(binding.session_id, ActorId("codex:other")))
        with self.assertRaises(StateHandleAuthorityError):
            handle.apply(event(SessionId("thread-b"), binding.actor_id))
        with self.assertRaises(StateHandleAuthorityError):
            handle.apply(
                event(
                    binding.session_id,
                    binding.actor_id,
                    MaterialActionKind.EXTERNAL_MUTATION,
                )
            )

        state = handle.apply(event(binding.session_id, binding.actor_id))
        self.assertIn(binding.actor_id, state.material_actions)


if __name__ == "__main__":  # pragma: no cover - test entrypoint
    import unittest

    unittest.main()

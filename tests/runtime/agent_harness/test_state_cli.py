"""Runtime-owned identity만으로 session control plane을 조작하는 CLI 계약입니다."""

import hashlib
import json
import subprocess
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from scripts.agent_harness.adaptive_control import (
    AuthorityReceipt,
    ControlAction,
    CriterionEvidence,
    CriterionSpec,
    EvidenceAuthority,
    EvidenceKind,
    EvidenceStatus,
    ExecutionStatus,
    GapInventory,
    GoalContract,
    GoalCoverage,
    OracleOwner,
    RequirementSection,
    approved_requirement_fingerprint,
)
from scripts.agent_harness.adaptive_control_authority import (
    AdaptiveControlAuthorityConflict,
    AdaptiveControlAuthorityInvalid,
)
from scripts.agent_harness.adaptive_control_store import (
    AdaptiveControlState,
    AdaptiveControlStateMissing,
    AdaptiveControlStore,
)
from scripts.agent_harness.adaptive_evaluation_candidate import (
    AdaptiveEvaluationCandidateStore,
)
from scripts.agent_harness.artifact_store import SessionArtifactStore
from scripts.agent_harness.enclave_store import (
    EnclaveConflict,
    EnclaveFact,
    EnclaveSnapshot,
    EnclaveStore,
)
from scripts.agent_harness.material_action import (
    MaterialActionResolution,
    ObservableDeltaKind,
    ObservableObservation,
    ToolReceipt,
    ToolReceiptOutcome,
    material_observable_digest,
)
from scripts.agent_harness.session_kernel import (
    ActorId,
    ActorKind,
    ActorLineageAssurance,
    ActorStarted,
    DelegationAssigned,
    DelegationConsumed,
    DelegationId,
    DelegationReported,
    DelegationResult,
    DelegationTopologyPolicy,
    ForegroundPromptAuthorityContext,
    ForegroundTurnClosed,
    ForegroundTurnOutcome,
    ForegroundTurnPrompted,
    ForegroundTurnProvisioned,
    ForegroundTurnReceipt,
    ForegroundTurnYielded,
    MaterialActionToolObserved,
    MaterialActionToolStarted,
    SessionId,
    SessionKernel,
    SessionLocator,
    WorkflowId,
)
from scripts.agent_harness.skill_state_store import SkillStateStore
from scripts.agent_harness.state_cli import StateCliApplication, StateCliResult
from scripts.agent_harness.state_handle import (
    RuntimeEnvironmentResolver,
    RuntimeIdentityBinding,
    StateHandle,
)
from scripts.agent_harness.worktree_registry import (
    CanonicalWorktreeIdentity,
    WorktreeClaim,
    WorktreeIdentityResolver,
    WorktreeRegistry,
)


class StateCliApplicationTest(TestCase):
    """CLI가 path selector 없이 exact session authority와 optimistic CAS를 지킵니다."""

    def setUp(self) -> None:
        """독립 Git repository와 runtime-neutral CLI application을 준비합니다."""
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.repository = Path(self.directory.name)
        subprocess.run(
            ("git", "init", "--quiet", str(self.repository)),
            check=True,
            capture_output=True,
            text=True,
        )
        self.locator = SessionLocator.from_worktree(self.repository)
        self.application = StateCliApplication(enclave_max_bytes=4_096)
        self.environment_a = {"CODEX_THREAD_ID": "session-a"}
        self.environment_b = {"CODEX_THREAD_ID": "session-b"}
        resolver = RuntimeEnvironmentResolver()
        for environment in (self.environment_a, self.environment_b):
            handle = StateHandle.initialize(self.locator, resolver.resolve(environment))
            handle.apply(
                ForegroundTurnProvisioned(
                    session_id=handle.session_id,
                    actor_id=handle.actor_id,
                    idempotency_key=f"fixture:provision:{handle.session_id}",
                )
            )

    def _run(
        self,
        arguments: tuple[str, ...],
        environment: dict[str, str] | None = None,
        cwd: Path | None = None,
    ) -> StateCliResult:
        """CLI를 현재 fixture repository와 선택한 runtime identity로 실행합니다."""
        return self.application.run(
            arguments,
            self.environment_a if environment is None else environment,
            self.repository if cwd is None else cwd,
        )

    def _payload(self, result: StateCliResult) -> dict[str, object]:
        """CLI stdout의 JSON object shape를 검증해 반환합니다."""
        payload: object = json.loads(result.stdout)
        if not isinstance(payload, dict):
            self.fail("state CLI output must be a JSON object")
        return payload

    def _object(self, value: object, label: str) -> dict[str, object]:
        """Nested CLI payload가 string-keyed JSON object인지 검증합니다."""
        if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
            self.fail(f"{label} must be a string-keyed JSON object")
        return {str(key): entry for key, entry in value.items()}

    def _adaptive_state(self, *, complete: bool) -> AdaptiveControlState:
        """Current source와 user authority에 결속된 complete 또는 incomplete state를 만듭니다."""
        source_revision = "approved-plan:1"
        goal = "Adaptive workflow를 authoritative하게 종료한다"
        constraints = ("SessionKernel lifecycle을 보존한다",)
        non_goals = ("새 state store를 만들지 않는다",)
        criterion = CriterionSpec(
            criterion_id="workflow-terminal",
            description="Workflow가 current goal authority에 따라 종료된다",
            source_requirement_id="REQ-workflow-terminal",
            approved_requirement_fingerprint=approved_requirement_fingerprint(
                goal,
                constraints,
                non_goals,
                1,
                source_revision,
            ),
            observer="state CLI caller",
            precondition="Adaptive control snapshot이 current workflow에 존재한다",
            stimulus="completed finalization을 요청한다",
            expected_outcome="COMPLETE authority가 있을 때만 workflow가 완료된다",
            oracle_owner=OracleOwner.USER,
            hard=True,
            required_evidence=frozenset({EvidenceKind.USER_ACCEPTANCE}),
        )
        contract = GoalContract(
            goal=goal,
            constraints=constraints,
            requirement_ids=frozenset({criterion.source_requirement_id}),
            criteria=(criterion,),
            non_goals=non_goals,
            intent_revision=1,
            source_revision=source_revision,
        )
        inventory = GapInventory(
            intent_revision=contract.intent_revision,
            source_revision="repo:current",
            assessed_sections=frozenset(RequirementSection),
            gaps=(),
        )
        if not complete:
            return AdaptiveControlState.empty(contract, inventory)

        def lineage(authority: EvidenceAuthority, issuer_id: str) -> AuthorityReceipt:
            """Test authority를 current goal revision에 결속합니다."""
            body = f"{authority.value}:{issuer_id}:{source_revision}"
            return AuthorityReceipt(
                authority=authority,
                issuer_id=issuer_id,
                subject_id="codex:session:session-a",
                intent_revision=contract.intent_revision,
                source_revision=source_revision,
                receipt_digest=hashlib.sha256(body.encode()).hexdigest(),
            )

        return AdaptiveControlState(
            contract=contract,
            inventory=inventory,
            evidence=(
                CriterionEvidence(
                    goal_fingerprint=contract.fingerprint,
                    criterion_id=criterion.criterion_id,
                    kind=EvidenceKind.USER_ACCEPTANCE,
                    authority=EvidenceAuthority.USER,
                    status=EvidenceStatus.PASS,
                    reference="user-approved terminal criterion",
                    lineage=lineage(EvidenceAuthority.USER, "user"),
                ),
            ),
            coverage=None,
            execution_status=ExecutionStatus.COMPLETED,
            observations=(),
        )

    def _seed_adaptive_state(self, workflow_id: str, *, complete: bool) -> int:
        """Exact session workflow에 real adaptive state를 저장하고 current revision을 반환합니다."""
        handle = StateHandle.attach(
            self.locator,
            RuntimeEnvironmentResolver().resolve(self.environment_a),
        )
        snapshot = AdaptiveControlStore(SkillStateStore(handle, WorkflowId(workflow_id))).update(
            lambda _current: self._adaptive_state(complete=complete)
        )
        return snapshot.workflow_revision

    def _workflow_payload_json(self, workflow_id: str) -> str:
        """Current workflow payload를 generic finalize의 exact-preservation input으로 만듭니다."""
        workflow = (
            SessionKernel(self.locator)
            .inspect(SessionId("session-a"))
            .workflows[WorkflowId(workflow_id)]
        )
        return json.dumps(workflow.to_payload()["payload"])

    def _seed_independent_adaptive_completion(self, workflow_id: str) -> int:
        """Consumed evaluator artifact에 결속된 COMPLETE state를 저장합니다."""
        handle = StateHandle.attach(
            self.locator,
            RuntimeEnvironmentResolver().resolve(self.environment_a),
        )
        evaluator_id = ActorId(f"codex:{workflow_id}-evaluator")
        delegation_id = DelegationId(f"{workflow_id}-evaluation")
        handle.apply(
            ActorStarted(
                session_id=handle.session_id,
                actor_id=evaluator_id,
                parent_actor_id=handle.actor_id,
                kind=ActorKind.SUBAGENT,
                idempotency_key=f"{workflow_id}:evaluator:start",
                lineage_assurance=ActorLineageAssurance.HOST_ATTESTED,
            )
        )
        evaluator = StateHandle.attach(
            self.locator,
            RuntimeIdentityBinding(
                runtime=handle.runtime,
                session_id=handle.session_id,
                actor_id=evaluator_id,
                root_actor_id=handle.actor_id,
            ),
        )
        source_revision = "approved-plan:independent"
        goal = "독립 authority로 adaptive workflow를 종료한다"
        constraints = ("Exact workflow delegation만 신뢰한다",)
        non_goals = ("USER enum label을 external authority로 취급하지 않는다",)
        criterion = CriterionSpec(
            criterion_id="independent-terminal",
            description="독립 evaluator가 workflow 완료를 판정한다",
            source_requirement_id="REQ-independent-terminal",
            approved_requirement_fingerprint=approved_requirement_fingerprint(
                goal,
                constraints,
                non_goals,
                1,
                source_revision,
            ),
            observer="독립 evaluator",
            precondition="Exact workflow와 evaluator assignment가 고정되어 있다",
            stimulus="completed finalization을 요청한다",
            expected_outcome="Consumed evaluator artifact가 완료를 승인한다",
            oracle_owner=OracleOwner.INDEPENDENT_EVALUATOR,
            hard=True,
            required_evidence=frozenset({EvidenceKind.INDEPENDENT_SEMANTIC}),
        )
        contract = GoalContract(
            goal=goal,
            constraints=constraints,
            requirement_ids=frozenset({criterion.source_requirement_id}),
            criteria=(criterion,),
            non_goals=non_goals,
            intent_revision=1,
            source_revision=source_revision,
        )
        criterion_claim: dict[str, object] = {
            "authority": EvidenceAuthority.INDEPENDENT_EVALUATOR.value,
            "claim_type": "criterion-evidence",
            "criterion_id": criterion.criterion_id,
            "evaluation_revision": 1,
            "goal_fingerprint": contract.fingerprint,
            "kind": EvidenceKind.INDEPENDENT_SEMANTIC.value,
            "reference": "independent:criterion",
            "status": EvidenceStatus.PASS.value,
        }
        coverage_claim: dict[str, object] = {
            "authority": EvidenceAuthority.INDEPENDENT_EVALUATOR.value,
            "claim_type": "goal-coverage",
            "criterion_ids": [criterion.criterion_id],
            "evaluation_revision": 1,
            "goal_alignment": 1.0,
            "goal_fingerprint": contract.fingerprint,
            "reference": "independent:coverage",
            "reward_hacking_risk": 0.0,
            "semantic_drift": 0.0,
            "status": EvidenceStatus.PASS.value,
            "uncertainty": 0.0,
        }
        completion_claim: dict[str, object] = {
            "authority": EvidenceAuthority.INDEPENDENT_EVALUATOR.value,
            "claim_type": "execution-completion",
            "goal_fingerprint": contract.fingerprint,
            "status": ExecutionStatus.COMPLETED.value,
        }
        trajectory_digest = AdaptiveEvaluationCandidateStore(
            handle,
            WorkflowId(workflow_id),
        ).current_trajectory_digest()
        report: dict[str, object] = {
            "blocking_findings": [],
            "claims": sorted(
                (criterion_claim, coverage_claim, completion_claim),
                key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")),
            ),
            "goal_fingerprint": contract.fingerprint,
            "intent_revision": contract.intent_revision,
            "kind": "adaptive-goal-evaluation",
            "source_revision": contract.source_revision,
            "summary": "adaptive goal evaluation passed",
            "trajectory_assessment": {
                "blocking_findings": [],
                "trajectory_digest": trajectory_digest,
                "verdict": "pass",
            },
            "verdict": "pass",
            "workflow_id": workflow_id,
        }
        artifact = SessionArtifactStore(evaluator).put_json({
            "delegation_id": str(delegation_id),
            "report": report,
            "schema": "neurath.delegation-result.v1",
            "target_agent_id": str(evaluator_id),
        })
        lineage = AuthorityReceipt(
            authority=EvidenceAuthority.INDEPENDENT_EVALUATOR,
            issuer_id=str(evaluator_id),
            subject_id=str(handle.actor_id),
            intent_revision=contract.intent_revision,
            source_revision=contract.source_revision,
            receipt_digest=artifact.reference.removeprefix("sha256:"),
            delegation_id=str(delegation_id),
        )
        state = AdaptiveControlState(
            contract=contract,
            inventory=GapInventory(
                intent_revision=contract.intent_revision,
                source_revision=contract.source_revision,
                assessed_sections=frozenset(RequirementSection),
                gaps=(),
            ),
            evidence=(
                CriterionEvidence(
                    goal_fingerprint=contract.fingerprint,
                    criterion_id=criterion.criterion_id,
                    kind=EvidenceKind.INDEPENDENT_SEMANTIC,
                    authority=EvidenceAuthority.INDEPENDENT_EVALUATOR,
                    status=EvidenceStatus.PASS,
                    reference="independent:criterion",
                    lineage=lineage,
                ),
            ),
            coverage=GoalCoverage(
                goal_fingerprint=contract.fingerprint,
                criterion_ids=frozenset({criterion.criterion_id}),
                authority=EvidenceAuthority.INDEPENDENT_EVALUATOR,
                status=EvidenceStatus.PASS,
                reference="independent:coverage",
                goal_alignment=1.0,
                semantic_drift=0.0,
                uncertainty=0.0,
                reward_hacking_risk=0.0,
                lineage=lineage,
            ),
            execution_status=ExecutionStatus.COMPLETED,
            observations=(),
        )
        prepared = self._run((
            "adaptive",
            "prepare-evaluation",
            "--workflow-id",
            workflow_id,
            "--state-json",
            json.dumps(state.to_payload()),
        ))
        self.assertEqual(0, prepared.exit_code, prepared.stdout)
        prepared_result = self._object(
            self._payload(prepared)["result"],
            "prepared adaptive evaluation",
        )
        assignment_json = prepared_result["assignment_json"]
        candidate_ref = prepared_result["candidate_ref"]
        self.assertIsInstance(assignment_json, str)
        self.assertIsInstance(candidate_ref, str)
        assert isinstance(assignment_json, str)
        assert isinstance(candidate_ref, str)
        handle.apply(
            DelegationAssigned(
                session_id=handle.session_id,
                delegation_id=delegation_id,
                owner_actor_id=handle.actor_id,
                target_actor_id=evaluator_id,
                assignment=assignment_json,
                idempotency_key=f"{delegation_id}:assign",
                topology_policy=DelegationTopologyPolicy.DIRECT_CHILD,
            )
        )
        evaluator_environment = {
            "CODEX_THREAD_ID": "session-a",
            "NEURATH_AGENT_SESSION_ID": "session-a",
            "NEURATH_AGENT_ACTOR_ID": str(evaluator_id),
            "NEURATH_AGENT_RUNTIME": "codex",
        }
        read_candidate = self._run(
            (
                "adaptive",
                "read-evaluation",
                "--workflow-id",
                workflow_id,
                "--assignment-json",
                assignment_json,
            ),
            evaluator_environment,
        )
        self.assertEqual(0, read_candidate.exit_code, read_candidate.stdout)
        read_result = self._object(
            self._payload(read_candidate)["result"],
            "read adaptive evaluation",
        )
        self.assertEqual(state.to_payload(), read_result["state"])
        self.assertEqual(candidate_ref, read_result["candidate_ref"])
        evaluator.apply(
            DelegationReported(
                session_id=evaluator.session_id,
                delegation_id=delegation_id,
                reporter_actor_id=evaluator_id,
                result=DelegationResult(
                    verdict="pass",
                    summary=json.dumps(
                        {
                            "candidate_ref": candidate_ref,
                            "summary": "adaptive goal evaluation passed",
                            "trajectory_digest": trajectory_digest,
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    ),
                    outcome_ref=artifact.reference,
                    blocking_findings=(),
                ),
                idempotency_key=f"{delegation_id}:report",
            )
        )
        handle.apply(
            DelegationConsumed(
                session_id=handle.session_id,
                delegation_id=delegation_id,
                consumer_actor_id=handle.actor_id,
                idempotency_key=f"{delegation_id}:consume",
            )
        )
        replaced = self._run((
            "adaptive",
            "replace",
            "--workflow-id",
            workflow_id,
            "--expected-revision",
            "0",
            "--state-json",
            json.dumps(state.to_payload()),
        ))
        self.assertEqual(0, replaced.exit_code, replaced.stdout)
        replaced_result = self._object(
            self._payload(replaced)["result"],
            "replaced adaptive completion",
        )
        revision = replaced_result["workflow_revision"]
        self.assertIsInstance(revision, int)
        assert isinstance(revision, int)
        return revision

    def test_manual_state_and_repository_selectors_are_rejected_as_typed_json(self) -> None:
        """CLI는 `--state`와 `--repository`로 runtime-owned session 선택을 우회하지 않습니다."""
        cases = (
            ("--state", "/tmp/foreign.json"),
            ("--repository", "/tmp/foreign-repository"),
        )

        for option, value in cases:
            with self.subTest(option=option):
                result = self._run((option, value, "session", "inspect"))
                payload = self._payload(result)

                error = self._object(payload["error"], "error")

                self.assertNotEqual(0, result.exit_code)
                self.assertEqual(False, payload["ok"])
                self.assertEqual("invalid-input", error["code"])

    def test_runtime_identity_keeps_two_sessions_isolated_in_one_repository(self) -> None:
        """같은 cwd에서 실행한 두 runtime session은 서로의 workflow를 조회하지 않습니다."""
        started = self._run((
            "workflow",
            "start",
            "--workflow-id",
            "workflow-a",
            "--kind",
            "checkpoint",
            "--goal",
            "Issue 42",
            "--payload-json",
            '{"phase":1}',
            "--idempotency-key",
            "workflow-a:start",
        ))
        inspected_a = self._run(("session", "inspect"))
        inspected_b = self._run(
            ("session", "inspect"),
            self.environment_b,
        )

        payload_started = self._payload(started)
        payload_a = self._payload(inspected_a)
        payload_b = self._payload(inspected_b)
        result_a = self._object(payload_a["result"], "session-a result")
        result_b = self._object(payload_b["result"], "session-b result")
        workflows_a = self._object(result_a["workflows"], "session-a workflows")
        workflows_b = self._object(result_b["workflows"], "session-b workflows")
        session_a = self._object(result_a["session"], "session-a identity")
        session_b = self._object(result_b["session"], "session-b identity")
        self.assertEqual(True, payload_started["ok"])
        self.assertIn("workflow-a", workflows_a)
        self.assertEqual({}, workflows_b)
        self.assertEqual("session-a", session_a["id"])
        self.assertEqual("session-b", session_b["id"])

    def test_stale_workflow_revision_is_a_typed_conflict_without_mutation(self) -> None:
        """Workflow CAS 원본이 stale이면 JSON conflict를 반환하고 latest payload를 보존합니다."""
        self._run((
            "workflow",
            "start",
            "--workflow-id",
            "workflow-a",
            "--kind",
            "process-ticket",
            "--payload-json",
            '{"phase":1}',
            "--idempotency-key",
            "workflow-a:start",
        ))
        advanced = self._run((
            "workflow",
            "advance",
            "--workflow-id",
            "workflow-a",
            "--expected-revision",
            "0",
            "--payload-json",
            '{"phase":2}',
            "--idempotency-key",
            "workflow-a:advance:2",
        ))

        stale = self._run((
            "workflow",
            "advance",
            "--workflow-id",
            "workflow-a",
            "--expected-revision",
            "0",
            "--payload-json",
            '{"phase":3}',
            "--idempotency-key",
            "workflow-a:advance:stale",
        ))

        self.assertEqual(0, advanced.exit_code)
        self.assertNotEqual(0, stale.exit_code)
        stale_payload = self._payload(stale)
        stale_error = self._object(stale_payload["error"], "stale error")
        self.assertEqual("revision-conflict", stale_error["code"])
        workflow = (
            SessionKernel(self.locator)
            .inspect(SessionId("session-a"))
            .workflows[WorkflowId("workflow-a")]
        )
        self.assertEqual(1, workflow.revision)
        self.assertEqual(2, workflow.payload["phase"])

    def test_adaptive_replace_initializes_updates_and_reads_one_exact_workflow(self) -> None:
        """한 typed replace command가 adaptive namespace를 만들고 갱신하며 sibling을 보존합니다."""
        self._run((
            "workflow",
            "start",
            "--workflow-id",
            "adaptive-command",
            "--kind",
            "plan-issues",
            "--goal",
            self._adaptive_state(complete=False).contract.goal,
            "--payload-json",
            '{"phase_run":{"phase":1},"skill_state":{"decision_log":[]}}',
            "--idempotency-key",
            "adaptive-command:start",
        ))
        initial = self._adaptive_state(complete=False)
        initialized = self._run((
            "adaptive",
            "replace",
            "--workflow-id",
            "adaptive-command",
            "--expected-revision",
            "0",
            "--state-json",
            json.dumps(initial.to_payload()),
        ))
        updated_state = AdaptiveControlState(
            contract=initial.contract,
            inventory=initial.inventory,
            evidence=initial.evidence,
            coverage=initial.coverage,
            execution_status=ExecutionStatus.FAILED,
            observations=initial.observations,
        )
        updated = self._run((
            "adaptive",
            "replace",
            "--workflow-id",
            "adaptive-command",
            "--expected-revision",
            "1",
            "--state-json",
            json.dumps(updated_state.to_payload()),
        ))
        inspected = self._run((
            "adaptive",
            "read",
            "--workflow-id",
            "adaptive-command",
        ))

        self.assertEqual(0, initialized.exit_code, initialized.stdout)
        self.assertEqual(0, updated.exit_code, updated.stdout)
        self.assertEqual(0, inspected.exit_code, inspected.stdout)
        result = self._object(self._payload(inspected)["result"], "adaptive read result")
        state = self._object(result["state"], "adaptive state")
        receipt = self._object(result["receipt"], "adaptive receipt")
        authority = self._object(result["authority"], "adaptive authority")
        self.assertEqual("adaptive-command", result["workflow_id"])
        self.assertEqual(2, result["workflow_revision"])
        self.assertEqual(updated_state.to_payload(), state)
        self.assertEqual(ControlAction.AWAIT_USER.value, receipt["action"])
        self.assertEqual("verified", authority["status"])
        self.assertEqual(True, authority["complete"])
        workflow = (
            SessionKernel(self.locator)
            .inspect(SessionId("session-a"))
            .workflows[WorkflowId("adaptive-command")]
        )
        self.assertEqual({"phase": 1}, workflow.payload["phase_run"])
        skill_state = self._object(workflow.payload["skill_state"], "workflow skill state")
        self.assertEqual([], skill_state["decision_log"])
        self.assertIn("adaptive_control", skill_state)

    def test_adaptive_override_goal_uses_explicit_typed_cas_boundary(self) -> None:
        """Explicit override도 exact typed USER decision이 없으면 goal을 바꾸지 못합니다."""
        workflow_id = "adaptive-goal-override"
        initial = self._adaptive_state(complete=False)
        started = self._run((
            "workflow",
            "start",
            "--workflow-id",
            workflow_id,
            "--kind",
            "plan-issues",
            "--goal",
            initial.contract.goal,
            "--payload-json",
            '{"skill_state":{}}',
            "--idempotency-key",
            f"{workflow_id}:start",
        ))
        self.assertEqual(0, started.exit_code, started.stdout)
        initialized = self._run((
            "adaptive",
            "replace",
            "--workflow-id",
            workflow_id,
            "--expected-revision",
            "0",
            "--state-json",
            json.dumps(initial.to_payload()),
        ))
        self.assertEqual(0, initialized.exit_code, initialized.stdout)
        source_revision = "approved-plan:2"
        constraints = (*initial.contract.constraints, "새 사용자 결정을 반영한다")
        criterion = replace(
            initial.contract.criteria[0],
            approved_requirement_fingerprint=approved_requirement_fingerprint(
                initial.contract.goal,
                constraints,
                initial.contract.non_goals,
                2,
                source_revision,
            ),
        )
        contract = GoalContract(
            goal=initial.contract.goal,
            constraints=constraints,
            requirement_ids=initial.contract.requirement_ids,
            criteria=(criterion,),
            non_goals=initial.contract.non_goals,
            intent_revision=2,
            source_revision=source_revision,
        )
        candidate = AdaptiveControlState.empty(
            contract,
            GapInventory(
                intent_revision=2,
                source_revision="repo:current",
                assessed_sections=frozenset(RequirementSection),
                gaps=(),
            ),
        )

        ordinary = self._run((
            "adaptive",
            "replace",
            "--workflow-id",
            workflow_id,
            "--expected-revision",
            "1",
            "--state-json",
            json.dumps(candidate.to_payload()),
        ))
        overridden = self._run((
            "adaptive",
            "override-goal",
            "--workflow-id",
            workflow_id,
            "--expected-revision",
            "1",
            "--state-json",
            json.dumps(candidate.to_payload()),
        ))

        self.assertEqual(2, ordinary.exit_code)
        self.assertEqual(2, overridden.exit_code)
        error = self._object(self._payload(overridden)["error"], "goal override error")
        self.assertEqual("state-error", error["code"])
        self.assertIn("typed USER decision", str(error["message"]))
        persisted = self._run(("adaptive", "read", "--workflow-id", workflow_id))
        result = self._object(self._payload(persisted)["result"], "adaptive read result")
        self.assertEqual(1, result["workflow_revision"])
        self.assertEqual(initial.to_payload(), result["state"])

    def test_generic_workflow_commands_preserve_reserved_adaptive_namespace_exactly(self) -> None:
        """Generic start/advance/finalize는 adaptive_control create/change/delete를 소유하지 않습니다."""
        adaptive = self._adaptive_state(complete=False)
        created = self._run((
            "workflow",
            "start",
            "--workflow-id",
            "reserved-create",
            "--kind",
            "plan-issues",
            "--payload-json",
            json.dumps({"skill_state": {"adaptive_control": adaptive.to_payload()}}),
            "--idempotency-key",
            "reserved-create:start",
        ))
        self.assertEqual(2, created.exit_code)
        self.assertEqual(
            "authority-denied",
            self._object(self._payload(created)["error"], "reserved create error")["code"],
        )

        workflow_id = "reserved-adaptive"
        started = self._run((
            "workflow",
            "start",
            "--workflow-id",
            workflow_id,
            "--kind",
            "plan-issues",
            "--goal",
            adaptive.contract.goal,
            "--payload-json",
            '{"phase":1,"skill_state":{"sibling":true}}',
            "--idempotency-key",
            f"{workflow_id}:start",
        ))
        self.assertEqual(0, started.exit_code, started.stdout)
        replaced = self._run((
            "adaptive",
            "replace",
            "--workflow-id",
            workflow_id,
            "--expected-revision",
            "0",
            "--state-json",
            json.dumps(adaptive.to_payload()),
        ))
        self.assertEqual(0, replaced.exit_code, replaced.stdout)
        handle = StateHandle.attach(
            self.locator,
            RuntimeEnvironmentResolver().resolve(self.environment_a),
        )
        current = handle.inspect().workflows[WorkflowId(workflow_id)]
        current_payload = json.loads(json.dumps(dict(current.payload)))
        self.assertIsInstance(current_payload, dict)
        assert isinstance(current_payload, dict)
        skill_state = self._object(current_payload["skill_state"], "reserved skill state")
        adaptive_payload = self._object(
            skill_state["adaptive_control"],
            "reserved adaptive payload",
        )
        modified_adaptive = {**adaptive_payload, "execution_status": "failed"}

        mutation_payloads = (
            {
                **current_payload,
                "skill_state": {**skill_state, "adaptive_control": modified_adaptive},
            },
            {
                **current_payload,
                "skill_state": {
                    key: value for key, value in skill_state.items() if key != "adaptive_control"
                },
            },
        )
        for index, payload in enumerate(mutation_payloads, start=1):
            with self.subTest(index=index):
                denied = self._run((
                    "workflow",
                    "advance",
                    "--workflow-id",
                    workflow_id,
                    "--expected-revision",
                    "1",
                    "--payload-json",
                    json.dumps(payload),
                    "--idempotency-key",
                    f"{workflow_id}:forbidden:{index}",
                ))
                self.assertEqual(2, denied.exit_code)
                self.assertEqual(
                    "authority-denied",
                    self._object(
                        self._payload(denied)["error"],
                        "reserved mutation error",
                    )["code"],
                )

        sibling_payload = {**current_payload, "phase": 2}
        advanced = self._run((
            "workflow",
            "advance",
            "--workflow-id",
            workflow_id,
            "--expected-revision",
            "1",
            "--payload-json",
            json.dumps(sibling_payload),
            "--idempotency-key",
            f"{workflow_id}:sibling",
        ))
        self.assertEqual(0, advanced.exit_code, advanced.stdout)
        after_advance = handle.inspect().workflows[WorkflowId(workflow_id)]
        after_skill_state = self._object(
            after_advance.payload["skill_state"],
            "preserved adaptive skill state",
        )
        self.assertEqual(adaptive_payload, after_skill_state["adaptive_control"])

        forbidden_final = self._run((
            "workflow",
            "finalize",
            "--workflow-id",
            workflow_id,
            "--expected-revision",
            "2",
            "--status",
            "failed",
            "--payload-json",
            json.dumps({
                **sibling_payload,
                "skill_state": {
                    key: value for key, value in skill_state.items() if key != "adaptive_control"
                },
            }),
            "--idempotency-key",
            f"{workflow_id}:forbidden-finalize",
        ))
        self.assertEqual(2, forbidden_final.exit_code)
        self.assertEqual(
            "authority-denied",
            self._object(
                self._payload(forbidden_final)["error"],
                "reserved finalize error",
            )["code"],
        )

        finalized = self._run((
            "workflow",
            "finalize",
            "--workflow-id",
            workflow_id,
            "--expected-revision",
            "2",
            "--status",
            "failed",
            "--payload-json",
            json.dumps(sibling_payload),
            "--idempotency-key",
            f"{workflow_id}:finalize",
        ))
        self.assertEqual(2, finalized.exit_code, finalized.stdout)
        self.assertEqual(
            after_advance.to_payload(),
            handle.inspect().workflows[WorkflowId(workflow_id)].to_payload(),
        )

    def test_adaptive_evaluation_candidate_cli_prepares_and_direct_child_reads(self) -> None:
        """Owner prepare와 assigned direct-child read만 full candidate를 path 없이 전달합니다."""
        workflow_id = "adaptive-evaluation-cli"
        state = self._adaptive_state(complete=False)
        started = self._run((
            "workflow",
            "start",
            "--workflow-id",
            workflow_id,
            "--kind",
            "evaluate-harness",
            "--goal",
            state.contract.goal,
            "--payload-json",
            '{"skill_state":{}}',
            "--idempotency-key",
            f"{workflow_id}:start",
        ))
        self.assertEqual(0, started.exit_code, started.stdout)
        owner = StateHandle.attach(
            self.locator,
            RuntimeEnvironmentResolver().resolve(self.environment_a),
        )
        evaluator_id = ActorId("codex:adaptive-evaluation-cli-child")
        owner.apply(
            ActorStarted(
                session_id=owner.session_id,
                actor_id=evaluator_id,
                parent_actor_id=owner.actor_id,
                kind=ActorKind.SUBAGENT,
                idempotency_key=f"{workflow_id}:child:start",
                lineage_assurance=ActorLineageAssurance.HOST_ATTESTED,
            )
        )

        prepared = self._run((
            "adaptive",
            "prepare-evaluation",
            "--workflow-id",
            workflow_id,
            "--state-json",
            json.dumps(state.to_payload()),
        ))
        self.assertEqual(0, prepared.exit_code, prepared.stdout)
        prepared_result = self._object(
            self._payload(prepared)["result"],
            "prepared candidate",
        )
        assignment_json = prepared_result["assignment_json"]
        self.assertIsInstance(assignment_json, str)
        assert isinstance(assignment_json, str)
        assigned = self._run((
            "delegation",
            "assign",
            "--delegation-id",
            f"{workflow_id}:delegation",
            "--target-actor-id",
            str(evaluator_id),
            "--assignment",
            assignment_json,
            "--topology-policy",
            "direct-child",
            "--idempotency-key",
            f"{workflow_id}:assign",
        ))
        self.assertEqual(0, assigned.exit_code, assigned.stdout)
        evaluator_environment = {
            "CODEX_THREAD_ID": "session-a",
            "NEURATH_AGENT_SESSION_ID": "session-a",
            "NEURATH_AGENT_ACTOR_ID": str(evaluator_id),
            "NEURATH_AGENT_RUNTIME": "codex",
        }
        child_read = self._run(
            (
                "adaptive",
                "read-evaluation",
                "--workflow-id",
                workflow_id,
                "--assignment-json",
                assignment_json,
            ),
            evaluator_environment,
        )
        owner_read = self._run((
            "adaptive",
            "read-evaluation",
            "--workflow-id",
            workflow_id,
            "--assignment-json",
            assignment_json,
        ))

        self.assertEqual(0, child_read.exit_code, child_read.stdout)
        child_result = self._object(
            self._payload(child_read)["result"],
            "child candidate read",
        )
        self.assertEqual(
            {"candidate_ref", "state", "trajectory", "workflow_id"},
            set(child_result),
        )
        self.assertEqual(state.to_payload(), child_result["state"])
        self.assertEqual(
            {
                "schema": "neurath.adaptive-evaluation-trajectory.v1",
                "material_action": None,
            },
            child_result["trajectory"],
        )
        self.assertEqual(2, owner_read.exit_code)
        owner_error = self._object(self._payload(owner_read)["error"], "owner read error")
        self.assertEqual("authority-denied", owner_error["code"])

    def test_adaptive_read_evaluation_rejects_assignment_after_sibling_revision(self) -> None:
        """Prepare 뒤 unrelated workflow mutation도 old assignment를 stale로 만듭니다."""
        workflow_id = "adaptive-evaluation-stale-cli"
        state = self._adaptive_state(complete=False)
        started = self._run((
            "workflow",
            "start",
            "--workflow-id",
            workflow_id,
            "--kind",
            "evaluate-harness",
            "--goal",
            state.contract.goal,
            "--payload-json",
            '{"skill_state":{}}',
            "--idempotency-key",
            f"{workflow_id}:start",
        ))
        self.assertEqual(0, started.exit_code, started.stdout)
        owner = StateHandle.attach(
            self.locator,
            RuntimeEnvironmentResolver().resolve(self.environment_a),
        )
        evaluator_id = ActorId("codex:adaptive-evaluation-stale-cli-child")
        owner.apply(
            ActorStarted(
                session_id=owner.session_id,
                actor_id=evaluator_id,
                parent_actor_id=owner.actor_id,
                kind=ActorKind.SUBAGENT,
                idempotency_key=f"{workflow_id}:child:start",
                lineage_assurance=ActorLineageAssurance.HOST_ATTESTED,
            )
        )
        prepared = self._run((
            "adaptive",
            "prepare-evaluation",
            "--workflow-id",
            workflow_id,
            "--state-json",
            json.dumps(state.to_payload()),
        ))
        self.assertEqual(0, prepared.exit_code, prepared.stdout)
        prepared_result = self._object(
            self._payload(prepared)["result"],
            "prepared stale candidate",
        )
        assignment_json = prepared_result["assignment_json"]
        self.assertIsInstance(assignment_json, str)
        assert isinstance(assignment_json, str)
        assigned = self._run((
            "delegation",
            "assign",
            "--delegation-id",
            f"{workflow_id}:delegation",
            "--target-actor-id",
            str(evaluator_id),
            "--assignment",
            assignment_json,
            "--topology-policy",
            "direct-child",
            "--idempotency-key",
            f"{workflow_id}:assign",
        ))
        self.assertEqual(0, assigned.exit_code, assigned.stdout)
        SkillStateStore(owner, WorkflowId(workflow_id)).update({"monitoring": True})

        child_read = self._run(
            (
                "adaptive",
                "read-evaluation",
                "--workflow-id",
                workflow_id,
                "--assignment-json",
                assignment_json,
            ),
            {
                "CODEX_THREAD_ID": "session-a",
                "NEURATH_AGENT_SESSION_ID": "session-a",
                "NEURATH_AGENT_ACTOR_ID": str(evaluator_id),
                "NEURATH_AGENT_RUNTIME": "codex",
            },
        )

        self.assertEqual(2, child_read.exit_code)
        error = self._object(self._payload(child_read)["error"], "stale candidate error")
        self.assertEqual("revision-conflict", error["code"])

    def test_adaptive_execute_evidence_runs_exact_node_and_returns_runtime_lineage(self) -> None:
        """Public CLI는 raw receipt input 없이 tracked pytest node를 직접 실행합니다."""
        subprocess.run(
            ("git", "config", "user.email", "fixture@example.invalid"),
            cwd=self.repository,
            check=True,
        )
        subprocess.run(
            ("git", "config", "user.name", "Fixture"),
            cwd=self.repository,
            check=True,
        )
        (self.repository / ".gitignore").write_text(
            ".agents/runs/\n.pytest_cache/\n__pycache__/\n",
            encoding="utf-8",
        )
        runtime_test = self.repository / "tests/test_cli_runtime.py"
        runtime_test.parent.mkdir(parents=True)
        runtime_test.write_text(
            "def test_passes():\n    assert True\n",
            encoding="utf-8",
        )
        subprocess.run(("git", "add", "."), cwd=self.repository, check=True)
        subprocess.run(
            ("git", "commit", "-qm", "runtime fixture"),
            cwd=self.repository,
            check=True,
        )
        state = self._executable_adaptive_state()
        started = self._run((
            "workflow",
            "start",
            "--workflow-id",
            "adaptive-execution-cli",
            "--kind",
            "evaluate-harness",
            "--goal",
            state.contract.goal,
            "--payload-json",
            '{"skill_state":{}}',
            "--idempotency-key",
            "adaptive-execution-cli:start",
        ))
        self.assertEqual(0, started.exit_code, started.stdout)

        executed = self._run((
            "adaptive",
            "execute-evidence",
            "--workflow-id",
            "adaptive-execution-cli",
            "--state-json",
            json.dumps(state.to_payload()),
            "--criterion-id",
            "runtime-proof",
            "--evidence-kind",
            EvidenceKind.EXAMPLE_TEST.value,
            "--pytest-node",
            "tests/test_cli_runtime.py::test_passes",
        ))

        self.assertEqual(0, executed.exit_code, executed.stdout)
        result = self._object(self._payload(executed)["result"], "execution result")
        evidence = self._object(result["evidence"], "runtime evidence")
        lineage = self._object(evidence["lineage"], "runtime lineage")
        self.assertEqual("harness:adaptive-execution", lineage["issuer_id"])
        self.assertEqual(EvidenceAuthority.EXECUTABLE.value, evidence["authority"])
        self.assertEqual(EvidenceStatus.PASS.value, evidence["status"])
        self.assertEqual(0, result["workflow_revision"])
        self.assertEqual("tests/test_cli_runtime.py::test_passes", result["pytest_node"])

    def _executable_adaptive_state(self) -> AdaptiveControlState:
        """CLI runtime receipt용 executable criterion을 갖는 incomplete state를 만듭니다."""
        goal = "CLI가 adaptive executable evidence를 실행한다"
        constraints = ("current worktree exact node를 사용한다",)
        non_goals = ("raw receipt JSON을 받지 않는다",)
        source_revision = "approved-plan:runtime"
        requirement = approved_requirement_fingerprint(
            goal,
            constraints,
            non_goals,
            1,
            source_revision,
        )
        contract = GoalContract(
            goal=goal,
            constraints=constraints,
            requirement_ids=frozenset({"REQ-runtime"}),
            criteria=(
                CriterionSpec(
                    criterion_id="runtime-proof",
                    description="Tracked pytest node가 PASS한다",
                    source_requirement_id="REQ-runtime",
                    approved_requirement_fingerprint=requirement,
                    observer="adaptive execution CLI",
                    precondition="tracked pytest node가 있다",
                    stimulus="CLI가 exact node를 실행한다",
                    expected_outcome="one or more tests pass",
                    oracle_owner=OracleOwner.EXECUTABLE,
                    hard=True,
                    required_evidence=frozenset({EvidenceKind.EXAMPLE_TEST}),
                ),
            ),
            non_goals=non_goals,
            intent_revision=1,
            source_revision=source_revision,
        )
        return AdaptiveControlState.empty(
            contract,
            GapInventory(
                intent_revision=contract.intent_revision,
                source_revision=contract.source_revision,
                assessed_sections=frozenset(RequirementSection),
                gaps=(),
            ),
        )

    def test_adaptive_replace_rejects_a_stale_revision_without_mutation(self) -> None:
        """Sibling commit 뒤 stale adaptive replace는 typed conflict이며 current state를 보존합니다."""
        self._run((
            "workflow",
            "start",
            "--workflow-id",
            "adaptive-stale-command",
            "--kind",
            "plan-issues",
            "--goal",
            self._adaptive_state(complete=False).contract.goal,
            "--payload-json",
            '{"skill_state":{}}',
            "--idempotency-key",
            "adaptive-stale-command:start",
        ))
        expected = self._adaptive_state(complete=False)
        self._run((
            "adaptive",
            "replace",
            "--workflow-id",
            "adaptive-stale-command",
            "--expected-revision",
            "0",
            "--state-json",
            json.dumps(expected.to_payload()),
        ))
        handle = StateHandle.attach(
            self.locator,
            RuntimeEnvironmentResolver().resolve(self.environment_a),
        )
        SkillStateStore(handle, WorkflowId("adaptive-stale-command")).update({"monitoring": True})

        stale = self._run((
            "adaptive",
            "replace",
            "--workflow-id",
            "adaptive-stale-command",
            "--expected-revision",
            "1",
            "--state-json",
            json.dumps(
                AdaptiveControlState(
                    contract=expected.contract,
                    inventory=expected.inventory,
                    evidence=expected.evidence,
                    coverage=expected.coverage,
                    execution_status=ExecutionStatus.FAILED,
                    observations=expected.observations,
                ).to_payload()
            ),
        ))

        self.assertEqual(2, stale.exit_code)
        error = self._object(self._payload(stale)["error"], "adaptive stale error")
        self.assertEqual("revision-conflict", error["code"])
        current = AdaptiveControlStore(
            SkillStateStore(handle, WorkflowId("adaptive-stale-command"))
        ).read()
        self.assertEqual(expected, current.state)
        self.assertEqual(2, current.workflow_revision)

    def test_adaptive_replace_denies_authority_before_committing_candidate(self) -> None:
        """Admission failure는 adaptive namespace와 workflow revision을 전혀 바꾸지 않습니다."""
        self._run((
            "workflow",
            "start",
            "--workflow-id",
            "adaptive-admission-denied",
            "--kind",
            "plan-issues",
            "--goal",
            self._adaptive_state(complete=True).contract.goal,
            "--payload-json",
            '{"skill_state":{}}',
            "--idempotency-key",
            "adaptive-admission-denied:start",
        ))
        candidate = self._adaptive_state(complete=True)

        with patch(
            "scripts.agent_harness.state_cli.AdaptiveControlAuthorityVerifier.validate_candidate",
            side_effect=AdaptiveControlAuthorityInvalid("forged independent authority"),
        ):
            denied = self._run((
                "adaptive",
                "replace",
                "--workflow-id",
                "adaptive-admission-denied",
                "--expected-revision",
                "0",
                "--state-json",
                json.dumps(candidate.to_payload()),
            ))

        self.assertEqual(2, denied.exit_code)
        error = self._object(self._payload(denied)["error"], "adaptive admission error")
        self.assertEqual("authority-denied", error["code"])
        handle = StateHandle.attach(
            self.locator,
            RuntimeEnvironmentResolver().resolve(self.environment_a),
        )
        workflow_id = WorkflowId("adaptive-admission-denied")
        with self.assertRaises(AdaptiveControlStateMissing):
            AdaptiveControlStore(SkillStateStore(handle, workflow_id)).read()
        self.assertEqual(0, handle.inspect().workflows[workflow_id].revision)

    def test_adaptive_read_keeps_unverified_user_authority_pending(self) -> None:
        """USER receipt는 independent coverage가 없으므로 attainment와 authority 모두 pending입니다."""
        self._run((
            "workflow",
            "start",
            "--workflow-id",
            "adaptive-user-pending",
            "--kind",
            "plan-issues",
            "--goal",
            self._adaptive_state(complete=True).contract.goal,
            "--payload-json",
            '{"skill_state":{}}',
            "--idempotency-key",
            "adaptive-user-pending:start",
        ))
        state = self._adaptive_state(complete=True)
        replaced = self._run((
            "adaptive",
            "replace",
            "--workflow-id",
            "adaptive-user-pending",
            "--expected-revision",
            "0",
            "--state-json",
            json.dumps(state.to_payload()),
        ))
        inspected = self._run((
            "adaptive",
            "read",
            "--workflow-id",
            "adaptive-user-pending",
        ))

        self.assertEqual(0, replaced.exit_code, replaced.stdout)
        self.assertEqual(0, inspected.exit_code, inspected.stdout)
        replaced_result = self._object(
            self._payload(replaced)["result"],
            "adaptive pending replace result",
        )
        replaced_authority = self._object(
            replaced_result["authority"],
            "adaptive pending replace authority",
        )
        result = self._object(self._payload(inspected)["result"], "adaptive pending result")
        receipt = self._object(result["receipt"], "adaptive pending receipt")
        authority = self._object(result["authority"], "adaptive pending authority")
        self.assertEqual(ControlAction.CONTINUE.value, receipt["action"])
        self.assertEqual("pending-unverifiable", replaced_authority["status"])
        self.assertEqual(False, replaced_authority["complete"])
        self.assertEqual("pending-unverifiable", authority["status"])
        self.assertEqual(False, authority["complete"])
        self.assertIsNone(authority["user_prompt_receipt"])

    def test_adaptive_read_exposes_current_user_receipt_metadata_without_raw_prompt(
        self,
    ) -> None:
        """Adaptive read는 current user prompt의 digest/provenance만 DX metadata로 노출합니다."""
        workflow_id = WorkflowId("adaptive-user-receipt")
        self._run((
            "workflow",
            "start",
            "--workflow-id",
            str(workflow_id),
            "--kind",
            "plan-issues",
            "--goal",
            self._adaptive_state(complete=False).contract.goal,
            "--payload-json",
            '{"skill_state":{}}',
            "--idempotency-key",
            "adaptive-user-receipt:start",
        ))
        base = self._adaptive_state(complete=False)
        awaiting_user = AdaptiveControlState(
            contract=base.contract,
            inventory=base.inventory,
            evidence=(),
            coverage=None,
            execution_status=ExecutionStatus.COMPLETED,
            observations=(),
        )
        replaced = self._run((
            "adaptive",
            "replace",
            "--workflow-id",
            str(workflow_id),
            "--expected-revision",
            "0",
            "--state-json",
            json.dumps(awaiting_user.to_payload()),
        ))
        self.assertEqual(0, replaced.exit_code, replaced.stdout)

        handle = StateHandle.attach(
            self.locator,
            RuntimeEnvironmentResolver().resolve(self.environment_a),
        )
        question = "현재 결과를 승인하시나요?"
        response = "승인합니다. 이 원문은 process-state에 남지 않아야 합니다."
        handle.apply(
            ForegroundTurnPrompted(
                session_id=handle.session_id,
                actor_id=handle.actor_id,
                vendor_turn_id="vendor-question",
                idempotency_key="adaptive-user-receipt:question:prompt",
            )
        )
        question_turn = handle.inspect().foreground_turns[handle.actor_id]
        handle.apply(
            ForegroundTurnYielded(
                session_id=handle.session_id,
                actor_id=handle.actor_id,
                expected_turn_revision=question_turn.revision,
                receipt=ForegroundTurnReceipt(
                    ForegroundTurnOutcome.AWAITING_INPUT,
                    question=question,
                ),
                idempotency_key="adaptive-user-receipt:question:yield",
            )
        )
        ready_turn = handle.inspect().foreground_turns[handle.actor_id]
        handle.apply(
            ForegroundTurnClosed(
                session_id=handle.session_id,
                actor_id=handle.actor_id,
                expected_turn_revision=ready_turn.revision,
                idempotency_key="adaptive-user-receipt:question:close",
            )
        )
        preceding_turn = handle.inspect().foreground_turns[handle.actor_id]
        workflow = handle.inspect().workflows[workflow_id]
        context = ForegroundPromptAuthorityContext(
            workflow_id=workflow_id,
            workflow_revision=workflow.revision,
            goal_fingerprint=awaiting_user.contract.fingerprint,
            intent_revision=awaiting_user.contract.intent_revision,
            source_revision=awaiting_user.contract.source_revision,
            criterion_ids=tuple(
                criterion.criterion_id for criterion in awaiting_user.contract.criteria
            ),
            claim_ids=("criterion:workflow-terminal",),
            control_action=ControlAction.AWAIT_USER.value,
            question_digest=hashlib.sha256(question.encode("utf-8")).hexdigest(),
            question_generation=preceding_turn.generation,
            question_turn_revision=preceding_turn.revision,
        )
        prompt_digest = hashlib.sha256(response.encode("utf-8")).hexdigest()
        handle.apply(
            ForegroundTurnPrompted(
                session_id=handle.session_id,
                actor_id=handle.actor_id,
                vendor_turn_id="vendor-user-response",
                idempotency_key="adaptive-user-receipt:response:prompt",
                prompt_digest=prompt_digest,
                authority_context=context,
            )
        )

        inspected = self._run((
            "adaptive",
            "read",
            "--workflow-id",
            str(workflow_id),
        ))

        self.assertEqual(0, inspected.exit_code, inspected.stdout)
        result = self._object(self._payload(inspected)["result"], "adaptive receipt result")
        authority = self._object(result["authority"], "adaptive receipt authority")
        receipt = self._object(
            authority["user_prompt_receipt"],
            "adaptive user prompt receipt",
        )
        receipt_context = self._object(receipt["authority_context"], "prompt context")
        self.assertEqual(prompt_digest, receipt["prompt_digest"])
        self.assertEqual("vendor-user-response", receipt["vendor_turn_id"])
        self.assertEqual(str(workflow_id), receipt_context["workflow_id"])
        self.assertEqual(["criterion:workflow-terminal"], receipt_context["claim_ids"])
        self.assertNotIn(response, json.dumps(result, ensure_ascii=False))

    def test_turn_yield_requires_outcome_specific_evidence(self) -> None:
        """각 terminal outcome은 정확히 대응하는 non-empty evidence 하나만 받습니다."""
        actor_id = ActorId("codex:session:session-a")
        SessionKernel(self.locator).apply(
            ForegroundTurnPrompted(
                session_id=SessionId("session-a"),
                actor_id=actor_id,
                vendor_turn_id=None,
                idempotency_key="turn:prompt",
            )
        )
        cases = (
            ("completed", "summary"),
            ("awaiting-input", "question"),
            ("failed", "reason"),
        )

        for outcome, evidence in cases:
            with self.subTest(outcome=outcome):
                missing = self._run((
                    "turn",
                    "yield",
                    "--expected-revision",
                    "0",
                    "--outcome",
                    outcome,
                ))
                payload = self._payload(missing)
                error = self._object(payload["error"], "turn evidence error")
                self.assertEqual(2, missing.exit_code)
                self.assertEqual("transition-rejected", error["code"])
                message = error["message"]
                self.assertIsInstance(message, str)
                assert isinstance(message, str)
                self.assertIn(f"requires {evidence}", message)

        inspected = self._run(("turn", "inspect"))
        result = self._object(self._payload(inspected)["result"], "turn result")
        self.assertEqual("active", result["status"])
        self.assertEqual(0, result["revision"])

        accepted = self._run((
            "turn",
            "yield",
            "--expected-revision",
            "0",
            "--outcome",
            "failed",
            "--reason",
            "bounded execution cannot continue",
        ))
        accepted_result = self._object(
            self._payload(accepted)["result"],
            "accepted turn result",
        )
        receipt = self._object(accepted_result["receipt"], "failed receipt")
        self.assertEqual(0, accepted.exit_code, accepted.stdout)
        self.assertEqual("ready-to-stop", accepted_result["status"])
        self.assertEqual("failed", receipt["outcome"])
        self.assertEqual("bounded execution cannot continue", receipt["reason"])

    def test_workflow_finalize_and_delegation_lifecycle_use_bound_actor_authority(self) -> None:
        """Workflow 종료와 delegation report/consume은 current actor identity로만 수행됩니다."""
        self._run((
            "workflow",
            "start",
            "--workflow-id",
            "workflow-a",
            "--kind",
            "checkpoint",
            "--payload-json",
            "{}",
            "--idempotency-key",
            "workflow-a:start",
        ))
        finalized = self._run((
            "workflow",
            "finalize",
            "--workflow-id",
            "workflow-a",
            "--expected-revision",
            "0",
            "--status",
            "completed",
            "--payload-json",
            '{"receipt":"artifact:42"}',
            "--idempotency-key",
            "workflow-a:finalize",
        ))
        root_actor_id = ActorId("codex:session:session-a")
        worker_actor_id = ActorId("codex:worker-a")
        SessionKernel(self.locator).apply(
            ActorStarted(
                session_id=SessionId("session-a"),
                actor_id=worker_actor_id,
                parent_actor_id=root_actor_id,
                kind=ActorKind.SUBAGENT,
                idempotency_key="worker-a:start",
            )
        )
        assigned = self._run((
            "delegation",
            "assign",
            "--delegation-id",
            "delegation-a",
            "--target-actor-id",
            str(worker_actor_id),
            "--assignment",
            "독립 검증",
            "--idempotency-key",
            "delegation-a:assign",
        ))
        worker_environment = {
            "CODEX_THREAD_ID": "session-a",
            "NEURATH_AGENT_SESSION_ID": "session-a",
            "NEURATH_AGENT_ACTOR_ID": str(worker_actor_id),
            "NEURATH_AGENT_RUNTIME": "codex",
        }
        reported = self._run(
            (
                "delegation",
                "report",
                "--delegation-id",
                "delegation-a",
                "--verdict",
                "pass",
                "--summary",
                "검증 통과",
                "--outcome-ref",
                "artifact:delegation-a",
                "--idempotency-key",
                "delegation-a:report",
            ),
            worker_environment,
        )
        consumed = self._run((
            "delegation",
            "consume",
            "--delegation-id",
            "delegation-a",
            "--idempotency-key",
            "delegation-a:consume",
        ))

        for result in (finalized, assigned, reported, consumed):
            self.assertEqual(0, result.exit_code, result.stdout)
        state = SessionKernel(self.locator).inspect(SessionId("session-a"))
        self.assertEqual("completed", state.workflows[WorkflowId("workflow-a")].status.value)
        self.assertEqual(
            "consumed",
            state.delegations[DelegationId("delegation-a")].status.value,
        )

    def test_semantic_and_unknown_workflows_cannot_finalize_without_adaptive_snapshot(self) -> None:
        """Known semantic과 unknown runtime workflow 모두 missing snapshot에서 fail closed합니다."""
        for workflow_kind in ("audit-spec", "custom-runtime-workflow"):
            with self.subTest(workflow_kind=workflow_kind):
                workflow_id = f"{workflow_kind}-without-adaptive"
                self._run((
                    "workflow",
                    "start",
                    "--workflow-id",
                    workflow_id,
                    "--kind",
                    workflow_kind,
                    "--payload-json",
                    "{}",
                    "--idempotency-key",
                    f"{workflow_id}:start",
                ))

                finalized = self._run((
                    "workflow",
                    "finalize",
                    "--workflow-id",
                    workflow_id,
                    "--expected-revision",
                    "0",
                    "--status",
                    "completed",
                    "--payload-json",
                    "{}",
                    "--idempotency-key",
                    f"{workflow_id}:finalize",
                ))

                self.assertEqual(2, finalized.exit_code)
                error = self._object(
                    self._payload(finalized)["error"],
                    "required adaptive error",
                )
                self.assertEqual("transition-rejected", error["code"])
                current = SessionKernel(self.locator).inspect(SessionId("session-a"))
                self.assertEqual(
                    "active",
                    current.workflows[WorkflowId(workflow_id)].status.value,
                )

    def test_completed_finalize_delegates_to_shared_completion_readback(self) -> None:
        """CLI boundary는 자체 완료 predicate 대신 exact current revision verifier를 호출합니다."""
        workflow_id = "adaptive-shared-completion-readback"
        goal = "독립 authority로 adaptive workflow를 종료한다"
        started = self._run((
            "workflow",
            "start",
            "--workflow-id",
            workflow_id,
            "--kind",
            "evaluate-harness",
            "--goal",
            goal,
            "--payload-json",
            '{"skill_state":{}}',
            "--idempotency-key",
            f"{workflow_id}:start",
        ))
        self.assertEqual(0, started.exit_code, started.stdout)
        revision = self._seed_independent_adaptive_completion(workflow_id)

        with (
            patch(
                "scripts.agent_harness.state_cli.AdaptiveControlAuthorityVerifier.verify_completion"
            ) as verify_completion,
            patch.object(SessionKernel, "_validate_adaptive_authority", return_value=None),
        ):
            finalized = self._run((
                "workflow",
                "finalize",
                "--workflow-id",
                workflow_id,
                "--expected-revision",
                str(revision),
                "--status",
                "completed",
                "--payload-json",
                self._workflow_payload_json(workflow_id),
                "--idempotency-key",
                f"{workflow_id}:finalize",
            ))

        self.assertEqual(0, finalized.exit_code, finalized.stdout)
        verify_completion.assert_called_once_with(revision)

    def test_adaptive_untrusted_receipts_cannot_finalize_completed(self) -> None:
        """Shared verifier의 semantic 또는 stale failure를 CLI가 typed diagnostic으로 보존합니다."""
        cases = (
            (
                "forged-complete",
                AdaptiveControlAuthorityInvalid("forged COMPLETE receipt"),
                "transition-rejected",
            ),
            (
                "await-user",
                AdaptiveControlAuthorityInvalid("ambiguity awaits user authority"),
                "transition-rejected",
            ),
            (
                "continue",
                AdaptiveControlAuthorityInvalid("goal is not achieved"),
                "transition-rejected",
            ),
            (
                "change-approach",
                AdaptiveControlAuthorityInvalid("current approach cannot complete"),
                "transition-rejected",
            ),
            (
                "promote-harness",
                AdaptiveControlAuthorityInvalid("harness promotion is not completion"),
                "transition-rejected",
            ),
            (
                "stale-complete",
                AdaptiveControlAuthorityConflict("completion revision is stale"),
                "revision-conflict",
            ),
        )

        for suffix, verifier_error, expected_code in cases:
            with self.subTest(case=suffix):
                workflow_id = f"adaptive-{suffix}"
                self._run((
                    "workflow",
                    "start",
                    "--workflow-id",
                    workflow_id,
                    "--kind",
                    "evaluate-harness",
                    "--goal",
                    self._adaptive_state(complete=False).contract.goal,
                    "--payload-json",
                    '{"skill_state":{}}',
                    "--idempotency-key",
                    f"{workflow_id}:start",
                ))
                current_revision = self._seed_adaptive_state(workflow_id, complete=False)

                with patch(
                    "scripts.agent_harness.state_cli.AdaptiveControlAuthorityVerifier."
                    "verify_completion",
                    side_effect=verifier_error,
                ) as verify_completion:
                    result = self._run((
                        "workflow",
                        "finalize",
                        "--workflow-id",
                        workflow_id,
                        "--expected-revision",
                        str(current_revision),
                        "--status",
                        "completed",
                        "--payload-json",
                        self._workflow_payload_json(workflow_id),
                        "--idempotency-key",
                        f"{workflow_id}:finalize",
                    ))
                verify_completion.assert_called_once_with(current_revision)

                workflow = (
                    SessionKernel(self.locator)
                    .inspect(SessionId("session-a"))
                    .workflows[WorkflowId(workflow_id)]
                )
                payload = self._payload(result)
                error = self._object(payload["error"], "adaptive completion error")
                self.assertEqual(2, result.exit_code)
                self.assertEqual(expected_code, error["code"])
                self.assertEqual("active", workflow.status.value)

    def test_adaptive_incomplete_workflow_cannot_finalize_completed(self) -> None:
        """실제 current incomplete state readback은 workflow completed 전이를 거부합니다."""
        self._run((
            "workflow",
            "start",
            "--workflow-id",
            "adaptive-incomplete",
            "--kind",
            "evaluate-harness",
            "--goal",
            self._adaptive_state(complete=False).contract.goal,
            "--payload-json",
            '{"skill_state":{}}',
            "--idempotency-key",
            "adaptive-incomplete:start",
        ))
        revision = self._seed_adaptive_state("adaptive-incomplete", complete=False)

        result = self._run((
            "workflow",
            "finalize",
            "--workflow-id",
            "adaptive-incomplete",
            "--expected-revision",
            str(revision),
            "--status",
            "completed",
            "--payload-json",
            self._workflow_payload_json("adaptive-incomplete"),
            "--idempotency-key",
            "adaptive-incomplete:finalize",
        ))

        self.assertEqual(2, result.exit_code)
        payload = self._payload(result)
        error = self._object(payload["error"], "adaptive incomplete error")
        self.assertEqual("transition-rejected", error["code"])
        workflow = (
            SessionKernel(self.locator)
            .inspect(SessionId("session-a"))
            .workflows[WorkflowId("adaptive-incomplete")]
        )
        self.assertEqual("active", workflow.status.value)

    def test_adaptive_user_labeled_complete_workflow_cannot_finalize_completed(self) -> None:
        """Runtime-backed user receipt 없이 USER enum만 붙인 COMPLETE는 거부합니다."""
        self._run((
            "workflow",
            "start",
            "--workflow-id",
            "adaptive-complete",
            "--kind",
            "evaluate-harness",
            "--goal",
            self._adaptive_state(complete=True).contract.goal,
            "--payload-json",
            '{"skill_state":{}}',
            "--idempotency-key",
            "adaptive-complete:start",
        ))
        revision = self._seed_adaptive_state("adaptive-complete", complete=True)

        result = self._run((
            "workflow",
            "finalize",
            "--workflow-id",
            "adaptive-complete",
            "--expected-revision",
            str(revision),
            "--status",
            "completed",
            "--payload-json",
            self._workflow_payload_json("adaptive-complete"),
            "--idempotency-key",
            "adaptive-complete:finalize",
        ))

        self.assertEqual(2, result.exit_code)
        payload = self._payload(result)
        error = self._object(payload["error"], "adaptive user authority error")
        self.assertEqual("transition-rejected", error["code"])
        workflow = (
            SessionKernel(self.locator)
            .inspect(SessionId("session-a"))
            .workflows[WorkflowId("adaptive-complete")]
        )
        self.assertEqual("active", workflow.status.value)

    def test_adaptive_consumed_independent_authority_can_finalize_completed(self) -> None:
        """Exact consumed evaluator artifact와 COMPLETE receipt가 함께 있으면 종료합니다."""
        self._run((
            "workflow",
            "start",
            "--workflow-id",
            "adaptive-independent-complete",
            "--kind",
            "evaluate-harness",
            "--goal",
            "독립 authority로 adaptive workflow를 종료한다",
            "--payload-json",
            '{"skill_state":{}}',
            "--idempotency-key",
            "adaptive-independent-complete:start",
        ))
        revision = self._seed_independent_adaptive_completion("adaptive-independent-complete")

        result = self._run((
            "workflow",
            "finalize",
            "--workflow-id",
            "adaptive-independent-complete",
            "--expected-revision",
            str(revision),
            "--status",
            "completed",
            "--payload-json",
            self._workflow_payload_json("adaptive-independent-complete"),
            "--idempotency-key",
            "adaptive-independent-complete:finalize",
        ))

        self.assertEqual(0, result.exit_code, result.stdout)
        workflow = (
            SessionKernel(self.locator)
            .inspect(SessionId("session-a"))
            .workflows[WorkflowId("adaptive-independent-complete")]
        )
        self.assertEqual("completed", workflow.status.value)

    def test_adaptive_workflow_failed_finalization_does_not_require_completion(self) -> None:
        """실패 종료는 adaptive goal 미달성을 정상 완료로 위장하지 않고 그대로 허용합니다."""
        self._run((
            "workflow",
            "start",
            "--workflow-id",
            "adaptive-failed",
            "--kind",
            "evaluate-harness",
            "--goal",
            self._adaptive_state(complete=False).contract.goal,
            "--payload-json",
            '{"skill_state":{}}',
            "--idempotency-key",
            "adaptive-failed:start",
        ))
        revision = self._seed_adaptive_state("adaptive-failed", complete=False)
        handle = StateHandle.attach(
            self.locator,
            RuntimeEnvironmentResolver().resolve(self.environment_a),
        )
        store = AdaptiveControlStore(SkillStateStore(handle, WorkflowId("adaptive-failed")))
        current_state = store.read().state
        failed = store.compare_and_update(
            revision,
            lambda _current: replace(current_state, execution_status=ExecutionStatus.FAILED),
        )
        revision = failed.workflow_revision
        payload = (
            SessionKernel(self.locator)
            .inspect(SessionId("session-a"))
            .workflows[WorkflowId("adaptive-failed")]
            .payload
        )

        with patch(
            "scripts.agent_harness.state_cli.AdaptiveControlStore.receipt",
            side_effect=AssertionError("failed finalization must not read completion authority"),
        ):
            result = self._run((
                "workflow",
                "finalize",
                "--workflow-id",
                "adaptive-failed",
                "--expected-revision",
                str(revision),
                "--status",
                "failed",
                "--payload-json",
                json.dumps(dict(payload)),
                "--idempotency-key",
                "adaptive-failed:finalize",
            ))

        self.assertEqual(0, result.exit_code, result.stdout)
        workflow = (
            SessionKernel(self.locator)
            .inspect(SessionId("session-a"))
            .workflows[WorkflowId("adaptive-failed")]
        )
        self.assertEqual("failed", workflow.status.value)

    def test_enclave_mutation_recomputes_digest_after_concurrent_conflict(self) -> None:
        """Implicit set은 latest snapshot을 다시 읽어 bounded optimistic retry로 수렴합니다."""
        self._run(("session", "inspect"))
        current = EnclaveStore(self.locator, max_bytes=4_096).read(SessionId("session-a"))
        original_set = EnclaveStore.set
        attempts = 0

        def conflict_once(
            store: EnclaveStore,
            session_id: SessionId,
            actor_id: ActorId,
            key: str,
            fact: EnclaveFact,
            *,
            expected_digest: str | None = None,
        ) -> EnclaveSnapshot:
            """첫 commit만 stale CAS로 만들고 두 번째 호출은 실제 store에 위임합니다."""
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise EnclaveConflict(str(expected_digest), "concurrent-digest")
            return original_set(
                store,
                session_id,
                actor_id,
                key,
                fact,
                expected_digest=expected_digest,
            )

        with patch.object(
            EnclaveStore,
            "set",
            autospec=True,
            side_effect=conflict_once,
        ) as mutation:
            result = self._run((
                "enclave",
                "set",
                "--key",
                "browser-policy",
                "--value",
                "browser allowed",
                "--source-kind",
                "user",
                "--source-turn-id",
                "turn-42",
            ))

        self.assertEqual(0, result.exit_code, result.stdout)
        self.assertEqual(2, mutation.call_count)
        self.assertEqual(current.digest, mutation.call_args_list[0].kwargs["expected_digest"])

    def test_enclave_mutation_exposes_conflict_after_bounded_retry_exhaustion(self) -> None:
        """계속 바뀌는 enclave는 무한 loop 대신 latest digest와 typed conflict를 반환합니다."""
        self._run(("session", "inspect"))
        current = EnclaveStore(self.locator, max_bytes=4_096).read(SessionId("session-a"))
        application = StateCliApplication(enclave_max_bytes=4_096, enclave_retry_limit=3)

        with patch.object(
            EnclaveStore,
            "set",
            side_effect=EnclaveConflict(current.digest, "concurrent-digest"),
        ) as mutation:
            result = application.run(
                (
                    "enclave",
                    "set",
                    "--key",
                    "browser-policy",
                    "--value",
                    "browser allowed",
                    "--source-kind",
                    "user",
                    "--source-turn-id",
                    "turn-42",
                ),
                self.environment_a,
                self.repository,
            )

        self.assertNotEqual(0, result.exit_code)
        payload = self._payload(result)
        error = self._object(payload["error"], "enclave conflict error")
        self.assertEqual("revision-conflict", error["code"])
        self.assertEqual(3, mutation.call_count)

    def test_enclave_show_set_delete_preserves_latest_only_contract(self) -> None:
        """Enclave CLI는 current fact를 표시하고 set/delete를 latest-only로 반영합니다."""
        set_result = self._run((
            "enclave",
            "set",
            "--key",
            "browser-policy",
            "--value",
            "browser allowed",
            "--source-kind",
            "user",
            "--source-turn-id",
            "turn-42",
        ))
        shown = self._run(("enclave", "show"))
        deleted = self._run(("enclave", "delete", "--key", "browser-policy"))

        for result in (set_result, shown, deleted):
            self.assertEqual(0, result.exit_code, result.stdout)
        shown_root = self._payload(shown)
        deleted_root = self._payload(deleted)
        shown_payload = self._object(shown_root["result"], "shown result")
        deleted_payload = self._object(deleted_root["result"], "deleted result")
        shown_snapshot = self._object(shown_payload["snapshot"], "shown snapshot")
        deleted_snapshot = self._object(deleted_payload["snapshot"], "deleted snapshot")
        shown_facts = self._object(shown_snapshot["facts"], "shown facts")
        deleted_facts = self._object(deleted_snapshot["facts"], "deleted facts")
        browser_policy = self._object(shown_facts["browser-policy"], "browser policy")
        self.assertEqual(
            "browser allowed",
            browser_policy["value"],
        )
        self.assertEqual({}, deleted_facts)
        self.assertIn("digest", deleted_payload)

    def test_caller_supplied_worktree_id_is_rejected_before_registry_mutation(self) -> None:
        """Worktree resource는 caller option이 아니라 execution cwd만으로 선택합니다."""
        for command in ("claim", "release"):
            with self.subTest(command=command):
                result = self._run(("worktree", command, "--worktree-id", "foreign"))
                payload = self._payload(result)
                error = self._object(payload["error"], "legacy worktree selector error")

                self.assertNotEqual(0, result.exit_code)
                self.assertEqual("invalid-input", error["code"])

        self.assertFalse(self.locator.worktree_registry_root.exists())

    def test_worktree_control_root_mismatch_fails_closed_before_registry_mutation(self) -> None:
        """Locator와 resolver가 다른 repository를 가리키면 claim을 생성하지 않습니다."""
        revision_before = SessionKernel(self.locator).inspect(SessionId("session-a")).revision
        identity = WorktreeIdentityResolver().resolve(self.repository)
        mismatched_identity = CanonicalWorktreeIdentity(
            worktree_id=identity.worktree_id,
            path=identity.path,
            repository_control_root=self.repository / "foreign-control-root",
        )

        with patch.object(
            WorktreeIdentityResolver,
            "resolve",
            autospec=True,
            return_value=mismatched_identity,
        ) as identity_lookup:
            result = self._run(("worktree", "claim"))

        payload = self._payload(result)
        error = self._object(payload["error"], "repository identity error")
        self.assertNotEqual(0, result.exit_code)
        self.assertEqual("repository-unavailable", error["code"])
        self.assertEqual(1, identity_lookup.call_count)
        self.assertEqual(
            revision_before,
            SessionKernel(self.locator).inspect(SessionId("session-a")).revision,
        )
        self.assertFalse(self.locator.worktree_registry_root.exists())

    def test_worktree_release_uses_canonical_current_claim_and_denies_non_owner(self) -> None:
        """Claim은 cwd identity를 쓰고 release는 current fenced claim 전체를 CAS로 씁니다."""
        nested = self.repository / "packages" / "fixture"
        nested.mkdir(parents=True)
        identity = WorktreeIdentityResolver().resolve(nested)
        claimed = self._run(("worktree", "claim"), cwd=nested)
        denied = self._run(
            ("worktree", "release"),
            self.environment_b,
            cwd=nested,
        )

        self.assertEqual(0, claimed.exit_code, claimed.stdout)
        claimed_payload = self._payload(claimed)
        claimed_result = self._object(claimed_payload["result"], "claimed result")
        self.assertEqual(str(identity.worktree_id), claimed_result["worktree_id"])
        self.assertEqual(str(identity.path), claimed_result["path"])
        self.assertNotEqual(0, denied.exit_code)
        denied_payload = self._payload(denied)
        denied_error = self._object(denied_payload["error"], "denied error")
        self.assertEqual("authority-denied", denied_error["code"])
        current = WorktreeRegistry(self.locator).get(identity.worktree_id)
        self.assertEqual(SessionId("session-a"), current.session_id)
        self.assertEqual(identity.path, current.path)

        original_release = WorktreeRegistry.release
        released_claims: list[WorktreeClaim] = []

        def release_current(
            registry: WorktreeRegistry,
            expected_claim: WorktreeClaim,
        ) -> None:
            """CLI가 읽은 exact fenced claim을 실제 registry CAS에 전달합니다."""
            released_claims.append(expected_claim)
            original_release(registry, expected_claim)

        with patch.object(
            WorktreeRegistry,
            "release",
            autospec=True,
            side_effect=release_current,
        ):
            released = self._run(("worktree", "release"), cwd=nested)

        self.assertEqual(0, released.exit_code, released.stdout)
        released_payload = self._payload(released)
        released_result = self._object(released_payload["result"], "released result")
        self.assertEqual(True, released_result["released"])
        self.assertEqual([current.to_payload()], [claim.to_payload() for claim in released_claims])

    def test_abandon_lost_posttool_keeps_unknown_outcome_and_exact_identity(self) -> None:
        """PostTool 유실은 exact owner의 명시적 중단으로만 UNKNOWN 보존하며 닫습니다."""
        source = self.repository / "lost.txt"
        source.write_text("changed", encoding="utf-8")
        handle = StateHandle.attach(
            self.locator,
            RuntimeEnvironmentResolver().resolve(self.environment_a),
        )
        handle.apply(
            ForegroundTurnProvisioned(
                session_id=handle.session_id,
                actor_id=handle.actor_id,
                idempotency_key="lost:provision",
            )
        )
        prepared = self._run((
            "action",
            "prepare",
            "--batch-id",
            "lost",
            "--kind",
            "local-mutation",
            "--target",
            str(source),
            "--expectations-json",
            json.dumps([
                {
                    "observable_id": str(source),
                    "expected_delta": "unchanged",
                    "expected_digest": None,
                }
            ]),
        ))
        self.assertEqual(0, prepared.exit_code, prepared.stdout)
        batch = handle.inspect().material_actions[handle.actor_id]
        handle.apply(
            MaterialActionToolStarted(
                session_id=handle.session_id,
                actor_id=handle.actor_id,
                batch_id=batch.batch_id,
                expected_batch_revision=batch.revision,
                invocation_id="lost-tool",
                tool_name="edit",
                request_digest="a" * 64,
                targets=batch.targets,
                idempotency_key="lost:start",
            )
        )
        wrong = self._run((
            "action",
            "abandon",
            "--batch-id",
            "lost",
            "--expected-revision",
            "1",
            "--invocation-id",
            "foreign-tool",
        ))
        self.assertNotEqual(0, wrong.exit_code)
        result = self._run((
            "action",
            "abandon",
            "--batch-id",
            "lost",
            "--expected-revision",
            "1",
            "--invocation-id",
            "lost-tool",
        ))
        self.assertEqual(0, result.exit_code, result.stdout)
        abandoned = handle.inspect().material_actions[handle.actor_id]
        self.assertIs(MaterialActionResolution.BLOCKED, abandoned.resolution)
        receipt = abandoned.invocations[0].receipt
        assert receipt is not None
        self.assertIs(ToolReceiptOutcome.UNKNOWN, receipt.outcome)
        self.assertEqual("a" * 64, receipt.request_digest)

    def test_material_action_cli_prepares_reads_and_resolves_exact_foreground_batch(
        self,
    ) -> None:
        """CLI는 current turn의 source-bound intent만 만들고 matching receipt 뒤 닫습니다."""
        source = self.repository / "src" / "example.py"
        source.parent.mkdir()
        source.write_text("value = 1\n", encoding="utf-8")
        before_digest = material_observable_digest(source)
        assert before_digest is not None
        final_bytes = b"value = 2\n"
        source.write_bytes(final_bytes)
        final_digest = material_observable_digest(source)
        assert final_digest is not None
        source.write_text("value = 1\n", encoding="utf-8")
        handle = StateHandle.attach(
            self.locator,
            RuntimeEnvironmentResolver().resolve(self.environment_a),
        )
        handle.apply(
            ForegroundTurnPrompted(
                session_id=handle.session_id,
                actor_id=handle.actor_id,
                vendor_turn_id="vendor-material-action",
                idempotency_key="material-action:turn",
            )
        )
        expectations_json = json.dumps((
            {
                "observable_id": str(source.resolve()),
                "expected_delta": ObservableDeltaKind.CHANGED.value,
                "expected_digest": final_digest,
            },
        ))

        prepared = self._run((
            "action",
            "prepare",
            "--batch-id",
            "batch-1",
            "--kind",
            "local-mutation",
            "--target",
            str(source),
            "--expectations-json",
            expectations_json,
        ))

        self.assertEqual(0, prepared.exit_code, prepared.stdout)
        persisted = handle.inspect().material_actions[handle.actor_id]
        self.assertEqual(1, persisted.sequence)
        self.assertEqual((str(source.resolve()),), persisted.targets)
        self.assertEqual(before_digest, persisted.expectations[0].baseline_digest)
        inspected = self._run(("action", "read"))
        self.assertEqual(0, inspected.exit_code, inspected.stdout)
        inspected_result = self._object(self._payload(inspected)["result"], "action read")
        inspected_batch = self._object(inspected_result["batch"], "action batch")
        self.assertEqual("batch-1", inspected_batch["batch_id"])

        started = handle.apply(
            MaterialActionToolStarted(
                session_id=handle.session_id,
                actor_id=handle.actor_id,
                batch_id=persisted.batch_id,
                expected_batch_revision=persisted.revision,
                invocation_id="tool-use-1",
                tool_name="edit",
                request_digest=hashlib.sha256(b"request").hexdigest(),
                targets=persisted.targets,
                idempotency_key="material-action:start",
            )
        ).material_actions[handle.actor_id]
        source.write_bytes(final_bytes)
        observed = handle.apply(
            MaterialActionToolObserved(
                session_id=handle.session_id,
                actor_id=handle.actor_id,
                batch_id=started.batch_id,
                expected_batch_revision=started.revision,
                invocation_id="tool-use-1",
                receipt=ToolReceipt(
                    receipt_id="post-tool:tool-use-1",
                    request_digest=hashlib.sha256(b"request").hexdigest(),
                    outcome=ToolReceiptOutcome.SUCCEEDED,
                    output_digest=hashlib.sha256(b"output").hexdigest(),
                    observations=(
                        ObservableObservation(
                            observable_id=str(source.resolve()),
                            current_digest=final_digest,
                        ),
                    ),
                ),
                idempotency_key="material-action:observe",
            )
        ).material_actions[handle.actor_id]

        resolved = self._run((
            "action",
            "resolve",
            "--batch-id",
            observed.batch_id,
            "--expected-revision",
            str(observed.revision),
            "--resolution",
            MaterialActionResolution.COMPLETED.value,
        ))

        self.assertEqual(0, resolved.exit_code, resolved.stdout)
        resolved_batch = handle.inspect().material_actions[handle.actor_id]
        self.assertEqual(MaterialActionResolution.COMPLETED, resolved_batch.resolution)

    def test_session_recovery_provisions_missing_root_turn_idempotently(self) -> None:
        """Legacy exact session은 raw JSON edit 없이 root provisional turn을 복구합니다."""
        environment = {"CODEX_THREAD_ID": "legacy-missing-turn"}
        StateHandle.initialize(
            self.locator,
            RuntimeEnvironmentResolver().resolve(environment),
        )
        handle = StateHandle.attach(
            self.locator,
            RuntimeEnvironmentResolver().resolve(environment),
        )
        self.assertNotIn(handle.actor_id, handle.inspect().foreground_turns)

        first = self._run(("session", "recover-foreground-turn"), environment)
        second = self._run(("session", "recover-foreground-turn"), environment)
        turn = handle.inspect().foreground_turns[handle.actor_id]

        self.assertEqual(0, first.exit_code, first.stdout)
        self.assertEqual(0, second.exit_code, second.stdout)
        self.assertEqual(1, turn.generation)
        self.assertEqual(0, turn.revision)
        self.assertIsNone(turn.vendor_turn_id)
        self.assertIsNone(turn.user_prompt_receipt)

    def test_session_recovery_rejects_non_root_actor(self) -> None:
        """Recovery command는 payload-selected child가 root turn을 대신 만들 수 없습니다."""
        root = StateHandle.attach(
            self.locator,
            RuntimeEnvironmentResolver().resolve(self.environment_a),
        )
        child_id = ActorId("codex:recovery-child")
        root.apply(
            ActorStarted(
                session_id=root.session_id,
                actor_id=child_id,
                parent_actor_id=root.actor_id,
                kind=ActorKind.SUBAGENT,
                idempotency_key="recovery-child:start",
            )
        )
        child_environment = {
            "CODEX_THREAD_ID": "session-a",
            "NEURATH_AGENT_SESSION_ID": "session-a",
            "NEURATH_AGENT_ACTOR_ID": str(child_id),
            "NEURATH_AGENT_RUNTIME": "codex",
        }

        result = self._run(("session", "recover-foreground-turn"), child_environment)

        self.assertEqual(2, result.exit_code)
        error = self._object(self._payload(result)["error"], "recovery error")
        self.assertEqual("authority-denied", error["code"])

    def test_material_action_cli_rejects_unbound_semantic_and_opaque_external_intent(
        self,
    ) -> None:
        """Semantic action은 adaptive goal이 필요하고 opaque external target은 열지 않습니다."""
        handle = StateHandle.attach(
            self.locator,
            RuntimeEnvironmentResolver().resolve(self.environment_a),
        )
        handle.apply(
            ForegroundTurnPrompted(
                session_id=handle.session_id,
                actor_id=handle.actor_id,
                vendor_turn_id="vendor-material-action-deny",
                idempotency_key="material-action:deny:turn",
            )
        )
        source = self.repository / "decision.md"
        source.write_text("before\n", encoding="utf-8")
        expectation = json.dumps((
            {
                "observable_id": str(source.resolve()),
                "expected_delta": ObservableDeltaKind.CHANGED.value,
                "expected_digest": hashlib.sha256(b"after\n").hexdigest(),
            },
        ))

        unbound = self._run((
            "action",
            "prepare",
            "--batch-id",
            "semantic-unbound",
            "--kind",
            "semantic-decision",
            "--target",
            str(source),
            "--expectations-json",
            expectation,
        ))
        external = self._run((
            "action",
            "prepare",
            "--batch-id",
            "external-opaque",
            "--kind",
            "external-mutation",
            "--target",
            "https://example.invalid/resource",
            "--expectations-json",
            expectation,
        ))

        for result in (unbound, external):
            with self.subTest(result=result.stdout):
                self.assertNotEqual(0, result.exit_code)
        self.assertNotIn(handle.actor_id, handle.inspect().material_actions)


if __name__ == "__main__":  # pragma: no cover - test entrypoint
    unittest.main()

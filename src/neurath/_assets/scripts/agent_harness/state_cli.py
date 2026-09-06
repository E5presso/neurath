"""Runtime-owned identity로 session control plane을 조작하는 path-free CLI입니다."""

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from enum import StrEnum
from pathlib import Path
from typing import NoReturn

from scripts.agent_harness.adaptive_control import EvidenceKind
from scripts.agent_harness.adaptive_control_authority import (
    AdaptiveControlAuthorityConflict,
    AdaptiveControlAuthorityError,
    AdaptiveControlAuthorityVerification,
    AdaptiveControlAuthorityVerifier,
)
from scripts.agent_harness.adaptive_control_store import (
    AdaptiveControlSnapshot,
    AdaptiveControlState,
    AdaptiveControlStore,
    InvalidAdaptiveControlState,
)
from scripts.agent_harness.adaptive_evaluation_candidate import (
    AdaptiveEvaluationCandidateAuthorityError,
    AdaptiveEvaluationCandidateConflict,
    AdaptiveEvaluationCandidateError,
    AdaptiveEvaluationCandidateStore,
)
from scripts.agent_harness.adaptive_execution_receipt import (
    AdaptiveExecutionReceiptAuthorityError,
    AdaptiveExecutionReceiptConflict,
    AdaptiveExecutionReceiptError,
    AdaptiveExecutionReceiptStore,
)
from scripts.agent_harness.adaptive_policy import requires_adaptive_control_for_workflow
from scripts.agent_harness.enclave_store import (
    EnclaveAuthorityError,
    EnclaveConflict,
    EnclaveFact,
    EnclaveSourceKind,
    EnclaveStore,
    EnclaveStoreError,
)
from scripts.agent_harness.evaluation_admission import EvaluationAdmissionPolicy
from scripts.agent_harness.material_action import (
    AdaptiveActionBinding,
    MaterialActionKind,
    MaterialActionResolution,
    ObservableDeltaKind,
    ObservableExpectation,
    canonical_material_target,
    material_observable_digest,
)
from scripts.agent_harness.session_kernel import (
    ActorId,
    DelegationAssigned,
    DelegationConsumed,
    DelegationId,
    DelegationReported,
    DelegationResult,
    DelegationTopologyPolicy,
    ForegroundTurnOutcome,
    ForegroundTurnProvisioned,
    ForegroundTurnReceipt,
    ForegroundTurnYielded,
    MaterialActionAbandoned,
    MaterialActionPrepared,
    MaterialActionResolved,
    RevisionConflict,
    SessionKernelError,
    SessionLocator,
    TransitionRejected,
    TurnId,
    WorkflowAdvanced,
    WorkflowFinalized,
    WorkflowId,
    WorkflowStarted,
    WorkflowStatus,
)
from scripts.agent_harness.skill_state_store import SkillStateConflict, SkillStateStore
from scripts.agent_harness.state_handle import (
    RuntimeEnvironmentResolver,
    RuntimeIdentityConflict,
    RuntimeIdentityUnavailable,
    StateHandle,
    StateHandleAuthorityError,
)
from scripts.agent_harness.worktree_registry import (
    CanonicalWorktreeIdentity,
    WorktreeClaim,
    WorktreeIdentityAmbiguous,
    WorktreeIdentityResolver,
    WorktreeIdentityUnavailable,
    WorktreeLeaseConflict,
    WorktreeRegistry,
    WorktreeRegistryError,
)


class StateCliDiagnostic(StrEnum):
    """CLI caller가 안정적으로 분기할 machine-readable 결과 code입니다."""

    INVALID_INPUT = "invalid-input"
    """Command 또는 JSON argument가 public contract를 만족하지 않습니다."""

    IDENTITY_UNAVAILABLE = "identity-unavailable"
    """Runtime-owned root session identity가 environment에 없습니다."""

    IDENTITY_CONFLICT = "identity-conflict"
    """Vendor identity와 Neurath actor binding이 서로 충돌합니다."""

    AUTHORITY_DENIED = "authority-denied"
    """Current session actor가 요청한 mutation을 소유하지 않습니다."""

    REVISION_CONFLICT = "revision-conflict"
    """Caller가 읽은 원본과 commit boundary의 current snapshot이 다릅니다."""

    TRANSITION_REJECTED = "transition-rejected"
    """Typed lifecycle event가 current aggregate 상태에서 허용되지 않습니다."""

    STATE_ERROR = "state-error"
    """Canonical state가 없거나 schema 또는 persistence contract를 위반합니다."""

    REPOSITORY_UNAVAILABLE = "repository-unavailable"
    """Execution cwd를 Git common control root로 해석할 수 없습니다."""


class StateCliError(RuntimeError):
    """Public CLI boundary가 typed JSON으로 반환할 application error입니다."""


class StateCliInputError(StateCliError):
    """Argument 또는 JSON payload가 public command contract를 위반했습니다."""


class StateCliAuthorityError(StateCliError):
    """Current runtime-bound actor가 resource mutation authority를 갖지 않습니다."""


class StateCliConfigurationError(StateCliError):
    """CLI application의 고정 enclave byte budget이 잘못됐습니다."""


class StateCliResult:
    """CLI process exit code와 단일 JSON stdout object를 결합합니다."""

    __slots__ = ("exit_code", "stdout")

    def __init__(self, *, exit_code: int, stdout: str) -> None:
        """외부 process adapter가 그대로 출력할 immutable 결과를 생성합니다.

        Args:
            exit_code: 성공이면 0, typed failure이면 0이 아닌 process code입니다.
            stdout: Success 또는 error envelope를 담은 JSON object 문자열입니다.
        """
        object.__setattr__(self, "exit_code", exit_code)
        object.__setattr__(self, "stdout", stdout)

    exit_code: int
    """CLI process가 caller에게 반환할 status code입니다."""

    stdout: str
    """Caller가 decode할 deterministic JSON object입니다."""

    def __setattr__(self, name: str, value: object) -> None:
        """생성된 CLI 결과의 변경을 거부합니다.

        Args:
            name: 변경을 시도한 attribute 이름입니다.
            value: Attribute에 새로 대입하려 한 값입니다.

        Raises:
            AttributeError: CLI 결과는 생성 뒤 immutable입니다.
        """
        raise AttributeError(f"{type(self).__name__} is immutable")


class StateCliOperation(StrEnum):
    """Argument parser가 선택한 closed command family입니다."""

    SESSION_INSPECT = "session-inspect"
    """Bound exact session의 current process-state를 조회합니다."""

    SESSION_RECOVER_FOREGROUND_TURN = "session-recover-foreground-turn"
    """Legacy exact root session에 provenance 없는 active turn을 복구합니다."""

    WORKFLOW_START = "workflow-start"
    """Current actor 소유의 새 workflow aggregate를 시작합니다."""

    WORKFLOW_ADVANCE = "workflow-advance"
    """Workflow-local revision CAS로 payload를 교체합니다."""

    WORKFLOW_FINALIZE = "workflow-finalize"
    """Workflow-local revision CAS로 terminal 결과를 확정합니다."""

    ADAPTIVE_READ = "adaptive-read"
    """Exact workflow의 canonical adaptive state와 authority read-back을 조회합니다."""

    ADAPTIVE_PREFLIGHT = "adaptive-preflight"
    """새 phase 생성 전에 현재 직접 자식 evaluator 가용성을 조회합니다."""

    ADAPTIVE_REPLACE = "adaptive-replace"
    """Typed adaptive state 전체를 workflow-local revision CAS로 교체합니다."""

    ADAPTIVE_OVERRIDE_GOAL = "adaptive-override-goal"
    """Typed old→new USER decision을 소비하며 goal contract를 명시적으로 교체합니다."""

    ADAPTIVE_PREPARE_EVALUATION = "adaptive-prepare-evaluation"
    """Owner가 full proposed adaptive state를 immutable evaluator artifact로 준비합니다."""

    ADAPTIVE_READ_EVALUATION = "adaptive-read-evaluation"
    """Assigned direct child가 exact evaluator candidate를 typed read-back합니다."""

    ADAPTIVE_EXECUTE_EVIDENCE = "adaptive-execute-evidence"
    """Owner가 tracked pytest node를 직접 실행해 content-addressed evidence를 발행합니다."""

    ACTION_PREPARE = "action-prepare"
    """Current foreground turn에 source-bound material action intent를 준비합니다."""

    ACTION_ABANDON = "action-abandon"
    """PostTool을 받지 못한 exact invocation을 UNKNOWN으로 보존하며 중단합니다."""

    ACTION_READ = "action-read"
    """Current actor의 latest bounded material action batch를 조회합니다."""

    ACTION_RESOLVE = "action-resolve"
    """Runtime receipt와 observable delta를 충족한 batch를 terminal 판정합니다."""

    TURN_INSPECT = "turn-inspect"
    """Current actor의 latest foreground turn을 조회합니다."""

    TURN_YIELD = "turn-yield"
    """Current actor가 optimistic CAS로 terminal control-return receipt를 제출합니다."""

    DELEGATION_ASSIGN = "delegation-assign"
    """Current actor가 target actor에 독립 assignment를 발행합니다."""

    DELEGATION_REPORT = "delegation-report"
    """Current target actor가 delegation result를 보고합니다."""

    DELEGATION_CONSUME = "delegation-consume"
    """Current owner actor가 reported delegation을 소비합니다."""

    ENCLAVE_SHOW = "enclave-show"
    """Bound exact session의 latest-only enclave를 조회합니다."""

    ENCLAVE_SET = "enclave-set"
    """Read digest를 원본으로 current enclave fact를 교체합니다."""

    ENCLAVE_DELETE = "enclave-delete"
    """Read digest를 원본으로 current enclave fact를 제거합니다."""

    WORKTREE_CLAIM = "worktree-claim"
    """Execution cwd worktree를 current actor에게 claim합니다."""

    WORKTREE_RELEASE = "worktree-release"
    """Read한 fenced claim 전체를 원본으로 current ownership을 해제합니다."""


class StateCliArgumentParser(argparse.ArgumentParser):
    """Argparse process exit을 typed application error로 변환합니다."""

    def error(self, message: str) -> NoReturn:
        """Parser error를 stdout JSON으로 변환 가능한 typed exception으로 올립니다.

        Args:
            message: Argparse가 생성한 구체적인 argument 위반 설명입니다.

        Returns:
            항상 typed exception을 발생시키므로 정상 반환하지 않습니다.

        Raises:
            StateCliInputError: 모든 parser error에서 항상 발생합니다.
        """
        raise StateCliInputError(message)


class StateCliApplication:
    """Runtime identity와 cwd에서만 canonical state services를 선택합니다."""

    def __init__(
        self,
        *,
        enclave_max_bytes: int = 65_536,
        enclave_retry_limit: int = 8,
    ) -> None:
        """Enclave snapshot의 고정 byte budget을 구성합니다.

        Args:
            enclave_max_bytes: CLI mutation 뒤 canonical enclave 전체의 최대 UTF-8 byte입니다.
            enclave_retry_limit: Implicit enclave CAS가 latest digest로 재계산할 상한입니다.

        Raises:
            StateCliConfigurationError: Byte budget이 양수가 아니면 발생합니다.
        """
        if enclave_max_bytes <= 0 or enclave_retry_limit <= 0:
            raise StateCliConfigurationError(
                "enclave_max_bytes and enclave_retry_limit must be positive"
            )
        self._enclave_max_bytes = enclave_max_bytes
        self._enclave_retry_limit = enclave_retry_limit
        self._resolver = RuntimeEnvironmentResolver()
        self._worktree_resolver = WorktreeIdentityResolver()

    def run(
        self,
        arguments: Sequence[str],
        environment: Mapping[str, object],
        cwd: Path,
    ) -> StateCliResult:
        """한 public command를 exact runtime session에 적용합니다.

        State path와 repository selector는 받지 않습니다. SessionLocator는 실행 cwd의
        Git common directory에서만 생성하고 StateHandle은 vendor-owned environment로만
        session과 current actor를 선택합니다.

        Args:
            arguments: `--state`, file input, repository selector가 없는 CLI arguments입니다.
            environment: Vendor identity와 optional validated Neurath actor binding입니다.
            cwd: 현재 CLI process가 실행된 repository 또는 linked worktree 경로입니다.

        Returns:
            성공 result 또는 typed JSON error와 nonzero exit code입니다.
        """
        try:
            namespace = self._parser().parse_args(tuple(arguments))
            locator = SessionLocator.from_worktree(cwd)
            worktree_identity = self._resolve_worktree_identity(namespace, locator, cwd)
            binding = self._resolver.resolve(environment)
            handle = StateHandle.attach(locator, binding)
            payload = self._execute(namespace, locator, handle, worktree_identity, cwd)
            return self._success(payload)
        except StateCliInputError as error:
            return self._failure(StateCliDiagnostic.INVALID_INPUT, str(error))
        except (WorktreeIdentityUnavailable, WorktreeIdentityAmbiguous) as error:
            return self._failure(StateCliDiagnostic.REPOSITORY_UNAVAILABLE, str(error))
        except RuntimeIdentityUnavailable as error:
            return self._failure(StateCliDiagnostic.IDENTITY_UNAVAILABLE, str(error))
        except RuntimeIdentityConflict as error:
            return self._failure(StateCliDiagnostic.IDENTITY_CONFLICT, str(error))
        except (StateHandleAuthorityError, EnclaveAuthorityError, StateCliAuthorityError) as error:
            return self._failure(StateCliDiagnostic.AUTHORITY_DENIED, str(error))
        except AdaptiveControlAuthorityConflict as error:
            return self._failure(StateCliDiagnostic.REVISION_CONFLICT, str(error))
        except AdaptiveControlAuthorityError as error:
            return self._failure(StateCliDiagnostic.AUTHORITY_DENIED, str(error))
        except AdaptiveEvaluationCandidateConflict as error:
            return self._failure(StateCliDiagnostic.REVISION_CONFLICT, str(error))
        except AdaptiveEvaluationCandidateAuthorityError as error:
            return self._failure(StateCliDiagnostic.AUTHORITY_DENIED, str(error))
        except AdaptiveEvaluationCandidateError as error:
            return self._failure(StateCliDiagnostic.STATE_ERROR, str(error))
        except AdaptiveExecutionReceiptConflict as error:
            return self._failure(StateCliDiagnostic.REVISION_CONFLICT, str(error))
        except AdaptiveExecutionReceiptAuthorityError as error:
            return self._failure(StateCliDiagnostic.AUTHORITY_DENIED, str(error))
        except AdaptiveExecutionReceiptError as error:
            return self._failure(StateCliDiagnostic.STATE_ERROR, str(error))
        except EnclaveConflict as error:
            return self._failure(
                StateCliDiagnostic.REVISION_CONFLICT,
                str(error),
                details={
                    "actual_digest": error.actual_digest,
                    "expected_digest": error.expected_digest,
                },
            )
        except WorktreeLeaseConflict as error:
            return self._failure(
                StateCliDiagnostic.REVISION_CONFLICT,
                str(error),
                details={"current_claim": error.current_claim.to_payload()},
            )
        except (RevisionConflict, SkillStateConflict) as error:
            return self._failure(StateCliDiagnostic.REVISION_CONFLICT, str(error))
        except TransitionRejected as error:
            diagnostic = (
                StateCliDiagnostic.REVISION_CONFLICT
                if str(error).startswith((
                    "expected workflow revision ",
                    "expected foreground turn revision ",
                    "expected material-action batch revision ",
                ))
                else StateCliDiagnostic.TRANSITION_REJECTED
            )
            return self._failure(diagnostic, str(error))
        except (SessionKernelError, EnclaveStoreError, WorktreeRegistryError) as error:
            return self._failure(StateCliDiagnostic.STATE_ERROR, str(error))
        except subprocess.CalledProcessError as error:
            return self._failure(StateCliDiagnostic.REPOSITORY_UNAVAILABLE, str(error))

    def _execute(
        self,
        namespace: argparse.Namespace,
        locator: SessionLocator,
        handle: StateHandle,
        worktree_identity: CanonicalWorktreeIdentity | None,
        cwd: Path,
    ) -> Mapping[str, object]:
        operation = namespace.operation
        if not isinstance(operation, StateCliOperation):
            raise StateCliInputError("a state command is required")
        if operation is StateCliOperation.SESSION_INSPECT:
            return handle.inspect().to_payload()
        if operation is StateCliOperation.SESSION_RECOVER_FOREGROUND_TURN:
            return self._recover_foreground_turn(handle)
        if operation is StateCliOperation.WORKFLOW_START:
            return self._start_workflow(namespace, handle)
        if operation is StateCliOperation.WORKFLOW_ADVANCE:
            return self._advance_workflow(namespace, handle)
        if operation is StateCliOperation.WORKFLOW_FINALIZE:
            return self._finalize_workflow(namespace, handle)
        if operation is StateCliOperation.ADAPTIVE_READ:
            return self._read_adaptive(namespace, handle)
        if operation is StateCliOperation.ADAPTIVE_PREFLIGHT:
            workflow_id = self._optional_text(namespace, "workflow_id")
            return EvaluationAdmissionPolicy().inspect(
                handle.inspect(),
                handle.actor_id,
                None if workflow_id is None else WorkflowId(workflow_id),
            )
        if operation is StateCliOperation.ADAPTIVE_REPLACE:
            return self._replace_adaptive(namespace, handle)
        if operation is StateCliOperation.ADAPTIVE_OVERRIDE_GOAL:
            return self._override_adaptive_goal(namespace, handle)
        if operation is StateCliOperation.ADAPTIVE_PREPARE_EVALUATION:
            return self._prepare_adaptive_evaluation(namespace, handle)
        if operation is StateCliOperation.ADAPTIVE_READ_EVALUATION:
            return self._read_adaptive_evaluation(namespace, handle)
        if operation is StateCliOperation.ADAPTIVE_EXECUTE_EVIDENCE:
            return self._execute_adaptive_evidence(namespace, handle)
        if operation is StateCliOperation.ACTION_PREPARE:
            return self._prepare_material_action(namespace, handle, cwd)
        if operation is StateCliOperation.ACTION_ABANDON:
            return self._abandon_material_action(namespace, handle)
        if operation is StateCliOperation.ACTION_READ:
            return self._read_material_action(handle)
        if operation is StateCliOperation.ACTION_RESOLVE:
            return self._resolve_material_action(namespace, handle)
        if operation is StateCliOperation.TURN_INSPECT:
            return self._inspect_turn(handle)
        if operation is StateCliOperation.TURN_YIELD:
            return self._yield_turn(namespace, handle)
        if operation is StateCliOperation.DELEGATION_ASSIGN:
            return self._assign_delegation(namespace, handle)
        if operation is StateCliOperation.DELEGATION_REPORT:
            return self._report_delegation(namespace, handle)
        if operation is StateCliOperation.DELEGATION_CONSUME:
            return self._consume_delegation(namespace, handle)
        if operation is StateCliOperation.ENCLAVE_SHOW:
            return self._show_enclave(locator, handle)
        if operation is StateCliOperation.ENCLAVE_SET:
            return self._set_enclave(namespace, locator, handle)
        if operation is StateCliOperation.ENCLAVE_DELETE:
            return self._delete_enclave(namespace, locator, handle)
        if operation in (
            StateCliOperation.WORKTREE_CLAIM,
            StateCliOperation.WORKTREE_RELEASE,
        ):
            if worktree_identity is None:
                raise StateCliConfigurationError(
                    "worktree operation is missing its canonical Git identity"
                )
            if operation is StateCliOperation.WORKTREE_CLAIM:
                return self._claim_worktree(locator, handle, worktree_identity)
            return self._release_worktree(locator, handle, worktree_identity)
        raise StateCliInputError(f"unsupported state command: {operation.value}")

    def _recover_foreground_turn(self, handle: StateHandle) -> Mapping[str, object]:
        """Current exact root session의 누락된 foreground turn만 typed event로 복구합니다."""
        state = handle.inspect()
        if handle.actor_id != state.session.root_actor_id:
            raise StateCliAuthorityError(
                "only the exact root actor can recover its foreground turn"
            )
        recovered = handle.apply(
            ForegroundTurnProvisioned(
                session_id=handle.session_id,
                actor_id=handle.actor_id,
                idempotency_key=f"session-recovery:foreground-turn:{handle.session_id}",
            )
        )
        return recovered.foreground_turns[handle.actor_id].to_payload()

    def _start_workflow(
        self,
        namespace: argparse.Namespace,
        handle: StateHandle,
    ) -> Mapping[str, object]:
        workflow_id = WorkflowId(self._text(namespace, "workflow_id"))
        payload = self._payload(namespace)
        self._require_reserved_adaptive_preserved(None, payload)
        state = handle.apply(
            WorkflowStarted(
                session_id=handle.session_id,
                workflow_id=workflow_id,
                owner_actor_id=handle.actor_id,
                kind=self._text(namespace, "kind"),
                goal=self._optional_text(namespace, "goal"),
                payload=payload,
                idempotency_key=self._text(namespace, "idempotency_key"),
            )
        )
        return state.workflows[workflow_id].to_payload()

    def _advance_workflow(
        self,
        namespace: argparse.Namespace,
        handle: StateHandle,
    ) -> Mapping[str, object]:
        workflow_id = WorkflowId(self._text(namespace, "workflow_id"))
        payload = self._payload(namespace)
        current = handle.inspect().workflows.get(workflow_id)
        if current is not None:
            self._require_reserved_adaptive_preserved(current.payload, payload)
        state = handle.apply(
            WorkflowAdvanced(
                session_id=handle.session_id,
                workflow_id=workflow_id,
                actor_id=handle.actor_id,
                expected_workflow_revision=self._integer(namespace, "expected_revision"),
                payload=payload,
                idempotency_key=self._text(namespace, "idempotency_key"),
            )
        )
        return state.workflows[workflow_id].to_payload()

    def _read_adaptive(
        self,
        namespace: argparse.Namespace,
        handle: StateHandle,
    ) -> Mapping[str, object]:
        """Exact workflow의 persisted state와 independently verified authority를 반환합니다."""
        workflow_id = WorkflowId(self._text(namespace, "workflow_id"))
        snapshot = AdaptiveControlStore(SkillStateStore(handle, workflow_id)).read()
        verification = AdaptiveControlAuthorityVerifier(handle, workflow_id).verify()
        if (
            verification.workflow_revision != snapshot.workflow_revision
            or verification.goal_fingerprint != snapshot.state.contract.fingerprint
        ):
            raise RevisionConflict(
                f"adaptive authority changed while reading workflow {workflow_id}"
            )
        return {
            **self._adaptive_snapshot_payload(snapshot),
            "authority": self._adaptive_authority_payload(verification),
        }

    def _replace_adaptive(
        self,
        namespace: argparse.Namespace,
        handle: StateHandle,
    ) -> Mapping[str, object]:
        """Canonical state 전체를 exact workflow revision에 한 번만 CAS합니다."""
        workflow_id = WorkflowId(self._text(namespace, "workflow_id"))
        candidate = self._adaptive_state(namespace)
        expected_revision = self._integer(namespace, "expected_revision")
        verifier = AdaptiveControlAuthorityVerifier(handle, workflow_id)
        verifier.validate_candidate(candidate, expected_revision)
        snapshot = AdaptiveControlStore(
            SkillStateStore(handle, workflow_id)
        ).compare_and_replace_payload(
            expected_revision,
            candidate.to_payload(),
        )
        verification = verifier.verify()
        if (
            verification.workflow_revision != snapshot.workflow_revision
            or verification.goal_fingerprint != snapshot.state.contract.fingerprint
        ):
            raise RevisionConflict(
                f"adaptive authority changed after replacing workflow {workflow_id}"
            )
        return {
            **self._adaptive_snapshot_payload(snapshot),
            "authority": self._adaptive_authority_payload(verification),
        }

    def _prepare_adaptive_evaluation(
        self,
        namespace: argparse.Namespace,
        handle: StateHandle,
    ) -> Mapping[str, object]:
        """Owner가 evaluator에게 위임할 exact full-state artifact를 content address합니다."""
        workflow_id = WorkflowId(self._text(namespace, "workflow_id"))
        prepared = AdaptiveEvaluationCandidateStore(handle, workflow_id).prepare(
            self._adaptive_state(namespace)
        )
        return {
            "assignment_json": prepared.assignment_json,
            "candidate_ref": prepared.candidate_ref,
            "workflow_id": str(workflow_id),
        }

    def _override_adaptive_goal(
        self,
        namespace: argparse.Namespace,
        handle: StateHandle,
    ) -> Mapping[str, object]:
        """Explicit goal override candidate를 authority 검증 뒤 exact CAS합니다."""
        workflow_id = WorkflowId(self._text(namespace, "workflow_id"))
        candidate = self._adaptive_state(namespace)
        expected_revision = self._integer(namespace, "expected_revision")
        verifier = AdaptiveControlAuthorityVerifier(handle, workflow_id)
        verifier.validate_candidate(candidate, expected_revision)
        snapshot = AdaptiveControlStore(
            SkillStateStore(handle, workflow_id)
        ).compare_and_override_payload(
            expected_revision,
            candidate.to_payload(),
        )
        verification = verifier.verify()
        if (
            verification.workflow_revision != snapshot.workflow_revision
            or verification.goal_fingerprint != snapshot.state.contract.fingerprint
        ):
            raise RevisionConflict(
                f"adaptive authority changed after overriding workflow {workflow_id}"
            )
        return {
            **self._adaptive_snapshot_payload(snapshot),
            "authority": self._adaptive_authority_payload(verification),
        }

    def _read_adaptive_evaluation(
        self,
        namespace: argparse.Namespace,
        handle: StateHandle,
    ) -> Mapping[str, object]:
        """Active direct child가 owner-issued assignment로만 immutable full state를 읽습니다."""
        workflow_id = WorkflowId(self._text(namespace, "workflow_id"))
        assignment_json = self._text(namespace, "assignment_json")
        candidate = AdaptiveEvaluationCandidateStore(handle, workflow_id).read_candidate(
            assignment_json
        )
        assignment: object = json.loads(assignment_json)
        if not isinstance(assignment, dict):
            raise StateCliInputError("assignment_json must be an object")
        candidate_ref = assignment.get("candidate_ref")
        if not isinstance(candidate_ref, str):
            raise StateCliInputError("assignment_json candidate_ref must be text")
        return {
            "candidate_ref": candidate_ref,
            "state": candidate.state.to_payload(),
            "trajectory": dict(candidate.trajectory),
            "workflow_id": str(workflow_id),
        }

    def _execute_adaptive_evidence(
        self,
        namespace: argparse.Namespace,
        handle: StateHandle,
    ) -> Mapping[str, object]:
        """Owner가 exact tracked pytest node를 실행하고 opaque runtime lineage를 받습니다."""
        workflow_id = WorkflowId(self._text(namespace, "workflow_id"))
        state = self._adaptive_state(namespace)
        evidence_kind = EvidenceKind(self._text(namespace, "evidence_kind"))
        issued = AdaptiveExecutionReceiptStore(handle, workflow_id).execute_pytest(
            state.contract,
            criterion_id=self._text(namespace, "criterion_id"),
            evidence_kind=evidence_kind,
            pytest_node=self._text(namespace, "pytest_node"),
        )
        evidence = issued.evidence
        lineage = evidence.lineage
        return {
            "evidence": {
                "authority": evidence.authority.value,
                "criterion_id": evidence.criterion_id,
                "evaluation_revision": evidence.evaluation_revision,
                "goal_fingerprint": evidence.goal_fingerprint,
                "kind": evidence.kind.value,
                "lineage": {
                    "authority": lineage.authority.value,
                    "delegation_id": lineage.delegation_id,
                    "intent_revision": lineage.intent_revision,
                    "issuer_id": lineage.issuer_id,
                    "receipt_digest": lineage.receipt_digest,
                    "source_revision": lineage.source_revision,
                    "subject_id": lineage.subject_id,
                },
                "reference": evidence.reference,
                "status": evidence.status.value,
            },
            "pytest_node": issued.pytest_node,
            "workflow_id": str(workflow_id),
            "workflow_revision": issued.workflow_revision,
            "worktree_fingerprint": issued.worktree_fingerprint,
        }

    def _prepare_material_action(
        self,
        namespace: argparse.Namespace,
        handle: StateHandle,
        cwd: Path,
    ) -> Mapping[str, object]:
        """Current foreground turn에 local observable baseline과 intent를 결속합니다."""
        try:
            kind = MaterialActionKind(self._text(namespace, "kind"))
        except ValueError as error:
            raise StateCliInputError("kind is not a supported material-action kind") from error
        if kind is MaterialActionKind.EXTERNAL_MUTATION:
            raise StateCliInputError(
                "external mutation requires an existing typed resource authority"
            )
        targets = self._material_targets(namespace, cwd)
        expectations = self._material_expectations(namespace, targets, cwd)
        binding = self._adaptive_action_binding(namespace, handle)
        if kind is MaterialActionKind.SEMANTIC_DECISION and binding is None:
            raise StateCliInputError("semantic decision requires --workflow-id adaptive authority")

        state = handle.inspect()
        turn = state.foreground_turns.get(handle.actor_id)
        if turn is None:
            raise TransitionRejected("material action requires an active foreground turn")
        batch_id = self._text(namespace, "batch_id")
        current = state.material_actions.get(handle.actor_id)
        if current is None:
            sequence = 1
        elif current.batch_id == batch_id:
            sequence = current.sequence
        else:
            sequence = current.sequence + 1
        committed = handle.apply(
            MaterialActionPrepared(
                session_id=handle.session_id,
                actor_id=handle.actor_id,
                batch_id=batch_id,
                sequence=sequence,
                expected_turn_generation=turn.generation,
                expected_turn_revision=turn.revision,
                kind=kind,
                targets=targets,
                expectations=expectations,
                adaptive_binding=binding,
                idempotency_key=f"material-action:prepare:{batch_id}",
            )
        )
        return committed.material_actions[handle.actor_id].to_payload()

    def _abandon_material_action(
        self,
        namespace: argparse.Namespace,
        handle: StateHandle,
    ) -> Mapping[str, object]:
        """유실된 PostTool을 성공으로 가장하지 않고 기존 typed abandonment로 정리합니다.

        Args:
            namespace: Caller가 읽은 exact batch revision과 invocation identity입니다.
            handle: Invocation을 소유하는 현재 runtime actor입니다.

        Returns:
            UNKNOWN receipt와 BLOCKED resolution을 보존한 canonical batch입니다.

        Raises:
            TransitionRejected: 현재 턴이 없거나 exact in-flight identity와 다릅니다.
        """
        state = handle.inspect()
        turn = state.foreground_turns.get(handle.actor_id)
        if turn is None:
            raise TransitionRejected("material-action abandonment requires current foreground turn")
        batch_id = self._text(namespace, "batch_id")
        invocation_id = self._text(namespace, "invocation_id")
        committed = handle.apply(
            MaterialActionAbandoned(
                session_id=handle.session_id,
                actor_id=handle.actor_id,
                batch_id=batch_id,
                expected_batch_revision=self._integer(namespace, "expected_revision"),
                expected_turn_generation=turn.generation,
                invocation_id=invocation_id,
                idempotency_key=f"material-action:abandon:{batch_id}:{invocation_id}:{turn.generation}",
            )
        )
        return committed.material_actions[handle.actor_id].to_payload()

    def _read_material_action(self, handle: StateHandle) -> Mapping[str, object]:
        """Current actor의 latest bounded batch를 raw command/output 없이 반환합니다."""
        batch = handle.inspect().material_actions.get(handle.actor_id)
        return {"batch": None if batch is None else batch.to_payload()}

    def _resolve_material_action(
        self,
        namespace: argparse.Namespace,
        handle: StateHandle,
    ) -> Mapping[str, object]:
        """Observed batch를 exact batch revision의 terminal resolution으로 닫습니다."""
        try:
            resolution = MaterialActionResolution(self._text(namespace, "resolution"))
        except ValueError as error:
            raise StateCliInputError("resolution is not a supported terminal value") from error
        batch_id = self._text(namespace, "batch_id")
        committed = handle.apply(
            MaterialActionResolved(
                session_id=handle.session_id,
                actor_id=handle.actor_id,
                batch_id=batch_id,
                expected_batch_revision=self._integer(namespace, "expected_revision"),
                resolution=resolution,
                idempotency_key=f"material-action:resolve:{batch_id}:{resolution.value}",
            )
        )
        return committed.material_actions[handle.actor_id].to_payload()

    def _material_targets(
        self,
        namespace: argparse.Namespace,
        cwd: Path,
    ) -> tuple[str, ...]:
        """Caller local paths를 current canonical worktree 안의 absolute target으로 바꿉니다."""
        identity = self._worktree_resolver.resolve(cwd)
        targets = tuple(
            self._canonical_local_target(raw, cwd, identity.path)
            for raw in self._string_sequence(namespace, "target")
        )
        if len(targets) != len(set(targets)):
            raise StateCliInputError("target entries must be unique after canonicalization")
        return tuple(sorted(targets))

    def _material_expectations(
        self,
        namespace: argparse.Namespace,
        targets: tuple[str, ...],
        cwd: Path,
    ) -> tuple[ObservableExpectation, ...]:
        """Expected final state는 받되 source baseline은 prepare boundary에서 직접 읽습니다."""
        raw = self._text(namespace, "expectations_json")
        try:
            payload: object = json.loads(raw)
        except json.JSONDecodeError as error:
            raise StateCliInputError("--expectations-json must be valid JSON") from error
        if not isinstance(payload, list) or not payload:
            raise StateCliInputError("--expectations-json must be a non-empty array")
        target_root = self._worktree_resolver.resolve(cwd).path
        expectations: list[ObservableExpectation] = []
        for item in payload:
            if not isinstance(item, dict) or any(not isinstance(key, str) for key in item):
                raise StateCliInputError("each material expectation must be an object")
            if set(item) != {"observable_id", "expected_delta", "expected_digest"}:
                raise StateCliInputError(
                    "material expectation must contain observable_id, expected_delta, expected_digest"
                )
            observable = item.get("observable_id")
            if not isinstance(observable, str) or not observable.strip():
                raise StateCliInputError("expectation observable_id must be a local path")
            observable_id = self._canonical_local_target(observable, cwd, target_root)
            try:
                expected_delta = ObservableDeltaKind(item.get("expected_delta"))
            except (TypeError, ValueError) as error:
                raise StateCliInputError("expectation expected_delta is invalid") from error
            expected_digest = item.get("expected_digest")
            if expected_digest is not None and (
                not isinstance(expected_digest, str)
                or len(expected_digest) != 64
                or any(character not in "0123456789abcdef" for character in expected_digest)
            ):
                raise StateCliInputError("expectation expected_digest must be SHA-256 or null")
            baseline = self._local_observable_digest(Path(observable_id))
            self._validate_material_transition(expected_delta, baseline, expected_digest)
            expectations.append(
                ObservableExpectation(
                    observable_id=observable_id,
                    baseline_digest=baseline,
                    expected_delta=expected_delta,
                    expected_digest=expected_digest,
                )
            )
        identities = tuple(item.observable_id for item in expectations)
        if len(identities) != len(set(identities)):
            raise StateCliInputError("expectation observable identities must be unique")
        if set(identities) != set(targets):
            raise StateCliInputError("local targets and observable expectations must match exactly")
        return tuple(sorted(expectations, key=lambda item: item.observable_id))

    def _canonical_local_target(self, raw: str, cwd: Path, root: Path) -> str:
        """Relative target를 resolve하고 symlink traversal과 foreign path를 거부합니다."""
        candidate = Path(raw)
        resolved = canonical_material_target(
            candidate if candidate.is_absolute() else cwd / candidate
        )
        canonical_root = root.resolve()
        if not resolved.is_relative_to(canonical_root):
            raise StateCliInputError("material-action target is outside the current worktree")
        if (resolved.exists() or resolved.is_symlink()) and not (
            resolved.is_file() or resolved.is_symlink()
        ):
            raise StateCliInputError("material-action local target must be a file or absent path")
        return str(resolved)

    def _local_observable_digest(self, target: Path) -> str | None:
        """Local file의 current mode+bytes digest를 읽고 부재를 별도 상태로 보존합니다."""
        try:
            return material_observable_digest(target)
        except OSError as error:
            raise StateCliInputError("material-action observable must be a regular file") from error

    def _validate_material_transition(
        self,
        kind: ObservableDeltaKind,
        baseline: str | None,
        expected: object,
    ) -> None:
        """Baseline과 expected final digest가 declared delta와 모순되지 않게 합니다."""
        if kind is ObservableDeltaKind.CREATED and baseline is not None:
            raise StateCliInputError("created expectation requires an absent baseline")
        if kind is ObservableDeltaKind.DELETED and (baseline is None or expected is not None):
            raise StateCliInputError(
                "deleted expectation requires existing baseline and null final"
            )
        if kind is ObservableDeltaKind.CHANGED and (
            baseline is None or expected is not None and baseline == expected
        ):
            raise StateCliInputError(
                "changed expectation requires an existing baseline and any supplied final digest must differ"
            )
        if kind is ObservableDeltaKind.UNCHANGED and (
            baseline is None or expected is not None and expected != baseline
        ):
            raise StateCliInputError(
                "unchanged expectation requires an existing baseline and any supplied digest must match"
            )

    def _adaptive_action_binding(
        self,
        namespace: argparse.Namespace,
        handle: StateHandle,
    ) -> AdaptiveActionBinding | None:
        """Optional workflow selector를 current adaptive goal/revision readback에 결속합니다."""
        raw_workflow_id = self._optional_text(namespace, "workflow_id")
        if raw_workflow_id is None:
            return None
        workflow_id = WorkflowId(raw_workflow_id)
        snapshot = AdaptiveControlStore(SkillStateStore(handle, workflow_id)).read()
        return AdaptiveActionBinding(
            workflow_id=str(workflow_id),
            workflow_revision=snapshot.workflow_revision,
            goal_fingerprint=snapshot.state.contract.fingerprint,
        )

    def _adaptive_snapshot_payload(
        self,
        snapshot: AdaptiveControlSnapshot,
    ) -> Mapping[str, object]:
        """Persisted state와 current derived receipt를 canonical CLI object로 변환합니다."""
        return {
            "workflow_id": str(snapshot.workflow_id),
            "workflow_revision": snapshot.workflow_revision,
            "state": snapshot.state.to_payload(),
            "receipt": snapshot.receipt().to_evidence(),
        }

    def _adaptive_authority_payload(
        self,
        verification: AdaptiveControlAuthorityVerification,
    ) -> Mapping[str, object]:
        """External verifier 결과를 read/replace가 공유하는 canonical object로 변환합니다."""
        return {
            "status": verification.status.value,
            "complete": verification.complete,
            "workflow_id": str(verification.workflow_id),
            "workflow_revision": verification.workflow_revision,
            "goal_fingerprint": verification.goal_fingerprint,
            "verified_delegation_ids": list(verification.verified_delegation_ids),
            "pending_claims": list(verification.pending_claims),
            "reason": verification.reason,
            "user_prompt_receipt": (
                None
                if verification.user_prompt_receipt is None
                else verification.user_prompt_receipt.to_payload()
            ),
        }

    def _finalize_workflow(
        self,
        namespace: argparse.Namespace,
        handle: StateHandle,
    ) -> Mapping[str, object]:
        workflow_id = WorkflowId(self._text(namespace, "workflow_id"))
        status = WorkflowStatus(self._text(namespace, "status"))
        expected_revision = self._integer(namespace, "expected_revision")
        payload = self._payload(namespace)
        current = handle.inspect().workflows.get(workflow_id)
        if current is not None:
            self._require_reserved_adaptive_preserved(current.payload, payload)
        if status is WorkflowStatus.COMPLETED:
            self._validate_adaptive_completion(
                handle,
                workflow_id,
                expected_revision,
            )
        state = handle.apply(
            WorkflowFinalized(
                session_id=handle.session_id,
                workflow_id=workflow_id,
                actor_id=handle.actor_id,
                expected_workflow_revision=expected_revision,
                terminal_status=status,
                payload=payload,
                idempotency_key=self._text(namespace, "idempotency_key"),
            )
        )
        return state.workflows[workflow_id].to_payload()

    def _require_reserved_adaptive_preserved(
        self,
        current_payload: Mapping[str, object] | None,
        candidate_payload: Mapping[str, object],
    ) -> None:
        """Generic workflow verbs가 typed adaptive namespace를 create/change/delete하지 못하게 합니다."""
        current_present, current_adaptive = self._adaptive_namespace(current_payload)
        candidate_present, candidate_adaptive = self._adaptive_namespace(candidate_payload)
        if not current_present and not candidate_present:
            return
        if current_present and candidate_present and current_adaptive == candidate_adaptive:
            return
        raise StateCliAuthorityError(
            "skill_state.adaptive_control is reserved for typed adaptive commands"
        )

    def _adaptive_namespace(
        self,
        payload: Mapping[str, object] | None,
    ) -> tuple[bool, object]:
        if payload is None:
            return False, None
        skill_state = payload.get("skill_state")
        if not isinstance(skill_state, Mapping) or "adaptive_control" not in skill_state:
            return False, None
        return True, skill_state["adaptive_control"]

    def _validate_adaptive_completion(
        self,
        handle: StateHandle,
        workflow_id: WorkflowId,
        expected_revision: int,
    ) -> None:
        """Adaptive workflow의 정상 완료를 exact current goal authority에 결속합니다.

        Adaptive namespace가 없는 legacy workflow에는 기존 SessionKernel transition을
        그대로 적용합니다. Namespace가 있으면 caller CAS 원본, 재계산 receipt revision,
        COMPLETE action과 두 achieved authority가 모두 일치해야 합니다.

        Args:
            handle: Runtime identity에 bound된 current actor authority입니다.
            workflow_id: 완료하려는 exact workflow identity입니다.
            expected_revision: Caller가 읽은 workflow-local CAS revision입니다.

        Raises:
            TransitionRejected: Adaptive completion authority가 current하지 않거나 미달이면
                발생합니다.
            SessionKernelError: Persisted adaptive state가 invalid하면 fail closed로 전파됩니다.
        """
        workflow = handle.inspect().workflows.get(workflow_id)
        if workflow is None:
            return
        skill_state = workflow.payload.get("skill_state")
        if not isinstance(skill_state, Mapping) or "adaptive_control" not in skill_state:
            try:
                required = requires_adaptive_control_for_workflow(
                    workflow.kind,
                    workflow.payload,
                )
            except (TypeError, ValueError) as error:
                raise TransitionRejected("persisted adaptive workflow policy is invalid") from error
            if required:
                raise TransitionRejected(
                    f"adaptive workflow {workflow_id} requires an adaptive_control snapshot"
                )
            return
        try:
            AdaptiveControlAuthorityVerifier(handle, workflow_id).verify_completion(
                expected_revision
            )
        except AdaptiveControlAuthorityConflict as error:
            raise RevisionConflict(
                f"adaptive authority changed while completing workflow {workflow_id}"
            ) from error
        except AdaptiveControlAuthorityError as error:
            raise TransitionRejected(
                f"adaptive workflow {workflow_id} has invalid completion authority"
            ) from error

    def _inspect_turn(self, handle: StateHandle) -> Mapping[str, object]:
        turn = handle.inspect().foreground_turns.get(handle.actor_id)
        if turn is None:
            raise TransitionRejected("foreground turn is missing")
        return turn.to_payload()

    def _yield_turn(
        self,
        namespace: argparse.Namespace,
        handle: StateHandle,
    ) -> Mapping[str, object]:
        outcome = ForegroundTurnOutcome(self._text(namespace, "outcome"))
        receipt = ForegroundTurnReceipt(
            outcome,
            summary=self._optional_text(namespace, "summary"),
            question=self._optional_text(namespace, "question"),
            reason=self._optional_text(namespace, "reason"),
        )
        expected_revision = self._integer(namespace, "expected_revision")
        current = handle.inspect().foreground_turns.get(handle.actor_id)
        if current is None:
            raise TransitionRejected("foreground turn is missing")
        state = handle.apply(
            ForegroundTurnYielded(
                session_id=handle.session_id,
                actor_id=handle.actor_id,
                expected_turn_revision=expected_revision,
                receipt=receipt,
                idempotency_key=(
                    f"foreground-turn:yield:{handle.actor_id}:{current.generation}:"
                    f"{expected_revision}:{outcome.value}"
                ),
            )
        )
        return state.foreground_turns[handle.actor_id].to_payload()

    def _assign_delegation(
        self,
        namespace: argparse.Namespace,
        handle: StateHandle,
    ) -> Mapping[str, object]:
        delegation_id = DelegationId(self._text(namespace, "delegation_id"))
        state = handle.apply(
            DelegationAssigned(
                session_id=handle.session_id,
                delegation_id=delegation_id,
                owner_actor_id=handle.actor_id,
                target_actor_id=ActorId(self._text(namespace, "target_actor_id")),
                assignment=self._text(namespace, "assignment"),
                idempotency_key=self._text(namespace, "idempotency_key"),
                topology_policy=DelegationTopologyPolicy(self._text(namespace, "topology_policy")),
            )
        )
        return state.delegations[delegation_id].to_payload()

    def _report_delegation(
        self,
        namespace: argparse.Namespace,
        handle: StateHandle,
    ) -> Mapping[str, object]:
        delegation_id = DelegationId(self._text(namespace, "delegation_id"))
        findings = self._string_sequence(namespace, "blocking_findings")
        state = handle.apply(
            DelegationReported(
                session_id=handle.session_id,
                delegation_id=delegation_id,
                reporter_actor_id=handle.actor_id,
                result=DelegationResult(
                    verdict=self._text(namespace, "verdict"),
                    summary=self._text(namespace, "summary"),
                    outcome_ref=self._text(namespace, "outcome_ref"),
                    blocking_findings=findings,
                ),
                idempotency_key=self._text(namespace, "idempotency_key"),
            )
        )
        return state.delegations[delegation_id].to_payload()

    def _consume_delegation(
        self,
        namespace: argparse.Namespace,
        handle: StateHandle,
    ) -> Mapping[str, object]:
        delegation_id = DelegationId(self._text(namespace, "delegation_id"))
        state = handle.apply(
            DelegationConsumed(
                session_id=handle.session_id,
                delegation_id=delegation_id,
                consumer_actor_id=handle.actor_id,
                idempotency_key=self._text(namespace, "idempotency_key"),
            )
        )
        return state.delegations[delegation_id].to_payload()

    def _show_enclave(
        self,
        locator: SessionLocator,
        handle: StateHandle,
    ) -> Mapping[str, object]:
        snapshot = self._enclaves(locator).read(handle.session_id)
        return {"digest": snapshot.digest, "snapshot": snapshot.to_payload()}

    def _set_enclave(
        self,
        namespace: argparse.Namespace,
        locator: SessionLocator,
        handle: StateHandle,
    ) -> Mapping[str, object]:
        enclaves = self._enclaves(locator)
        key = self._text(namespace, "key")
        fact = EnclaveFact(
            value=self._text(namespace, "value"),
            source_kind=EnclaveSourceKind(self._text(namespace, "source_kind")),
            source_turn_id=TurnId(self._text(namespace, "source_turn_id")),
        )
        conflict: EnclaveConflict | None = None
        for _attempt in range(self._enclave_retry_limit):
            original = enclaves.read(handle.session_id)
            try:
                snapshot = enclaves.set(
                    handle.session_id,
                    handle.actor_id,
                    key,
                    fact,
                    expected_digest=original.digest,
                )
            except EnclaveConflict as error:
                conflict = error
                continue
            return {"digest": snapshot.digest, "snapshot": snapshot.to_payload()}
        if conflict is None:
            raise StateCliConfigurationError("enclave retry loop did not execute")
        raise conflict

    def _delete_enclave(
        self,
        namespace: argparse.Namespace,
        locator: SessionLocator,
        handle: StateHandle,
    ) -> Mapping[str, object]:
        enclaves = self._enclaves(locator)
        key = self._text(namespace, "key")
        conflict: EnclaveConflict | None = None
        for _attempt in range(self._enclave_retry_limit):
            original = enclaves.read(handle.session_id)
            try:
                snapshot = enclaves.delete(
                    handle.session_id,
                    handle.actor_id,
                    key,
                    expected_digest=original.digest,
                )
            except EnclaveConflict as error:
                conflict = error
                continue
            return {"digest": snapshot.digest, "snapshot": snapshot.to_payload()}
        if conflict is None:
            raise StateCliConfigurationError("enclave retry loop did not execute")
        raise conflict

    def _claim_worktree(
        self,
        locator: SessionLocator,
        handle: StateHandle,
        identity: CanonicalWorktreeIdentity,
    ) -> Mapping[str, object]:
        registry = WorktreeRegistry(locator)
        claim = registry.claim(
            WorktreeClaim(
                worktree_id=identity.worktree_id,
                path=identity.path,
                session_id=handle.session_id,
                actor_id=handle.actor_id,
            )
        )
        return claim.to_payload()

    def _release_worktree(
        self,
        locator: SessionLocator,
        handle: StateHandle,
        identity: CanonicalWorktreeIdentity,
    ) -> Mapping[str, object]:
        registry = WorktreeRegistry(locator)
        current = registry.get(identity.worktree_id)
        if current.path != identity.path:
            raise WorktreeIdentityAmbiguous(
                "current worktree claim path differs from canonical Git identity"
            )
        if current.session_id != handle.session_id or current.actor_id != handle.actor_id:
            raise StateCliAuthorityError("current runtime actor does not own the worktree claim")
        registry.release(current)
        return {"claim": current.to_payload(), "released": True}

    def _resolve_worktree_identity(
        self,
        namespace: argparse.Namespace,
        locator: SessionLocator,
        cwd: Path,
    ) -> CanonicalWorktreeIdentity | None:
        operation = getattr(namespace, "operation", None)
        if operation not in (
            StateCliOperation.WORKTREE_CLAIM,
            StateCliOperation.WORKTREE_RELEASE,
        ):
            return None
        identity = self._worktree_resolver.resolve(cwd)
        if identity.repository_control_root != locator.control_root:
            raise WorktreeIdentityAmbiguous(
                "SessionLocator and worktree resolver disagree on repository control root"
            )
        return identity

    def _enclaves(self, locator: SessionLocator) -> EnclaveStore:
        return EnclaveStore(locator, max_bytes=self._enclave_max_bytes)

    def _payload(self, namespace: argparse.Namespace) -> Mapping[str, object]:
        raw_payload = self._text(namespace, "payload_json")
        try:
            payload: object = json.loads(raw_payload)
        except json.JSONDecodeError as error:
            raise StateCliInputError("--payload-json must be valid JSON") from error
        if not isinstance(payload, dict) or any(not isinstance(key, str) for key in payload):
            raise StateCliInputError("--payload-json must be a string-keyed JSON object")
        return {str(key): value for key, value in payload.items()}

    def _adaptive_state(self, namespace: argparse.Namespace) -> AdaptiveControlState:
        raw_state = self._text(namespace, "state_json")
        try:
            payload: object = json.loads(raw_state)
        except json.JSONDecodeError as error:
            raise StateCliInputError("--state-json must be valid JSON") from error
        if not isinstance(payload, dict) or any(not isinstance(key, str) for key in payload):
            raise StateCliInputError("--state-json must be a string-keyed JSON object")
        try:
            return AdaptiveControlState.from_payload({
                str(key): value for key, value in payload.items()
            })
        except InvalidAdaptiveControlState as error:
            raise StateCliInputError(str(error)) from error

    def _text(self, namespace: argparse.Namespace, name: str) -> str:
        value = getattr(namespace, name, None)
        if not isinstance(value, str) or not value.strip():
            raise StateCliInputError(f"{name} must be a non-empty string")
        return value.strip()

    def _optional_text(self, namespace: argparse.Namespace, name: str) -> str | None:
        value = getattr(namespace, name, None)
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            raise StateCliInputError(f"{name} must be omitted or non-empty")
        return value.strip()

    def _integer(self, namespace: argparse.Namespace, name: str) -> int:
        value = getattr(namespace, name, None)
        if not isinstance(value, int) or isinstance(value, bool):
            raise StateCliInputError(f"{name} must be an integer")
        return value

    def _string_sequence(
        self,
        namespace: argparse.Namespace,
        name: str,
    ) -> tuple[str, ...]:
        value = getattr(namespace, name, None)
        if not isinstance(value, list) or any(
            not isinstance(item, str) or not item.strip() for item in value
        ):
            raise StateCliInputError(f"{name} must contain non-empty strings")
        return tuple(item.strip() for item in value)

    def _success(self, payload: Mapping[str, object]) -> StateCliResult:
        return StateCliResult(
            exit_code=0,
            stdout=self._json({"ok": True, "result": dict(payload)}),
        )

    def _failure(
        self,
        diagnostic: StateCliDiagnostic,
        message: str,
        *,
        details: Mapping[str, object] | None = None,
    ) -> StateCliResult:
        error: dict[str, object] = {"code": diagnostic.value, "message": message}
        if details is not None:
            error["details"] = dict(details)
        return StateCliResult(
            exit_code=2,
            stdout=self._json({"error": error, "ok": False}),
        )

    def _json(self, payload: Mapping[str, object]) -> str:
        return json.dumps(
            dict(payload),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    def _parser(self) -> StateCliArgumentParser:
        parser = StateCliArgumentParser(
            description="Operate Neurath session state from runtime-owned identity.",
        )
        domains = parser.add_subparsers(dest="domain", required=True)
        self._session_parser(domains)
        self._turn_parser(domains)
        self._workflow_parser(domains)
        self._adaptive_parser(domains)
        self._action_parser(domains)
        self._delegation_parser(domains)
        self._enclave_parser(domains)
        self._worktree_parser(domains)
        return parser

    def _session_parser(
        self,
        domains: argparse._SubParsersAction[StateCliArgumentParser],
    ) -> None:
        session = domains.add_parser("session")
        commands = session.add_subparsers(dest="session_command", required=True)
        inspect = commands.add_parser("inspect")
        inspect.set_defaults(operation=StateCliOperation.SESSION_INSPECT)
        recover = commands.add_parser("recover-foreground-turn")
        recover.set_defaults(operation=StateCliOperation.SESSION_RECOVER_FOREGROUND_TURN)

    def _workflow_parser(
        self,
        domains: argparse._SubParsersAction[StateCliArgumentParser],
    ) -> None:
        workflow = domains.add_parser("workflow")
        commands = workflow.add_subparsers(dest="workflow_command", required=True)
        start = commands.add_parser("start")
        self._workflow_identity_arguments(start)
        start.add_argument("--kind", required=True)
        start.add_argument("--goal")
        start.set_defaults(operation=StateCliOperation.WORKFLOW_START)

        advance = commands.add_parser("advance")
        self._workflow_identity_arguments(advance)
        advance.add_argument("--expected-revision", required=True, type=int)
        advance.set_defaults(operation=StateCliOperation.WORKFLOW_ADVANCE)

        finalize = commands.add_parser("finalize")
        self._workflow_identity_arguments(finalize)
        finalize.add_argument("--expected-revision", required=True, type=int)
        finalize.add_argument(
            "--status",
            choices=(WorkflowStatus.COMPLETED.value, WorkflowStatus.FAILED.value),
            required=True,
        )
        finalize.set_defaults(operation=StateCliOperation.WORKFLOW_FINALIZE)

    def _adaptive_parser(
        self,
        domains: argparse._SubParsersAction[StateCliArgumentParser],
    ) -> None:
        adaptive = domains.add_parser("adaptive")
        commands = adaptive.add_subparsers(dest="adaptive_command", required=True)
        preflight = commands.add_parser("preflight")
        preflight.add_argument("--workflow-id")
        preflight.set_defaults(operation=StateCliOperation.ADAPTIVE_PREFLIGHT)
        read = commands.add_parser("read")
        read.add_argument("--workflow-id", required=True)
        read.set_defaults(operation=StateCliOperation.ADAPTIVE_READ)

        replace = commands.add_parser("replace")
        replace.add_argument("--workflow-id", required=True)
        replace.add_argument("--expected-revision", required=True, type=int)
        replace.add_argument("--state-json", required=True)
        replace.set_defaults(operation=StateCliOperation.ADAPTIVE_REPLACE)

        override_goal = commands.add_parser("override-goal")
        override_goal.add_argument("--workflow-id", required=True)
        override_goal.add_argument("--expected-revision", required=True, type=int)
        override_goal.add_argument("--state-json", required=True)
        override_goal.set_defaults(operation=StateCliOperation.ADAPTIVE_OVERRIDE_GOAL)

        prepare_evaluation = commands.add_parser("prepare-evaluation")
        prepare_evaluation.add_argument("--workflow-id", required=True)
        prepare_evaluation.add_argument("--state-json", required=True)
        prepare_evaluation.set_defaults(operation=StateCliOperation.ADAPTIVE_PREPARE_EVALUATION)

        read_evaluation = commands.add_parser("read-evaluation")
        read_evaluation.add_argument("--workflow-id", required=True)
        read_evaluation.add_argument("--assignment-json", required=True)
        read_evaluation.set_defaults(operation=StateCliOperation.ADAPTIVE_READ_EVALUATION)

        execute_evidence = commands.add_parser("execute-evidence")
        execute_evidence.add_argument("--workflow-id", required=True)
        execute_evidence.add_argument("--state-json", required=True)
        execute_evidence.add_argument("--criterion-id", required=True)
        execute_evidence.add_argument(
            "--evidence-kind",
            required=True,
            choices=(
                EvidenceKind.EXAMPLE_TEST.value,
                EvidenceKind.PROPERTY_TEST.value,
                EvidenceKind.METAMORPHIC_TEST.value,
                EvidenceKind.MUTATION_TEST.value,
            ),
        )
        execute_evidence.add_argument("--pytest-node", required=True)
        execute_evidence.set_defaults(operation=StateCliOperation.ADAPTIVE_EXECUTE_EVIDENCE)

    def _action_parser(
        self,
        domains: argparse._SubParsersAction[StateCliArgumentParser],
    ) -> None:
        """Material mutation의 prepare/read/resolve control-plane commands를 등록합니다."""
        action = domains.add_parser("action")
        commands = action.add_subparsers(dest="action_command", required=True)
        prepare = commands.add_parser("prepare")
        prepare.add_argument("--batch-id", required=True)
        prepare.add_argument(
            "--kind",
            required=True,
            choices=tuple(kind.value for kind in MaterialActionKind),
        )
        prepare.add_argument("--target", action="append", required=True)
        prepare.add_argument("--expectations-json", required=True)
        prepare.add_argument("--workflow-id")
        prepare.set_defaults(operation=StateCliOperation.ACTION_PREPARE)

        read = commands.add_parser("read")
        read.set_defaults(operation=StateCliOperation.ACTION_READ)

        abandon = commands.add_parser("abandon")
        abandon.add_argument("--batch-id", required=True)
        abandon.add_argument("--expected-revision", type=int, required=True)
        abandon.add_argument("--invocation-id", required=True)
        abandon.set_defaults(operation=StateCliOperation.ACTION_ABANDON)

        resolve = commands.add_parser("resolve")
        resolve.add_argument("--batch-id", required=True)
        resolve.add_argument("--expected-revision", required=True, type=int)
        resolve.add_argument(
            "--resolution",
            required=True,
            choices=tuple(item.value for item in MaterialActionResolution),
        )
        resolve.set_defaults(operation=StateCliOperation.ACTION_RESOLVE)

    def _turn_parser(
        self,
        domains: argparse._SubParsersAction[StateCliArgumentParser],
    ) -> None:
        turn = domains.add_parser("turn")
        commands = turn.add_subparsers(dest="turn_command", required=True)
        inspect = commands.add_parser("inspect")
        inspect.set_defaults(operation=StateCliOperation.TURN_INSPECT)
        yield_command = commands.add_parser("yield")
        yield_command.add_argument("--expected-revision", required=True, type=int)
        yield_command.add_argument(
            "--outcome",
            required=True,
            choices=tuple(outcome.value for outcome in ForegroundTurnOutcome),
        )
        yield_command.add_argument("--summary")
        yield_command.add_argument("--question")
        yield_command.add_argument("--reason")
        yield_command.set_defaults(operation=StateCliOperation.TURN_YIELD)

    def _workflow_identity_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--workflow-id", required=True)
        parser.add_argument("--payload-json", default="{}")
        parser.add_argument("--idempotency-key", required=True)

    def _delegation_parser(
        self,
        domains: argparse._SubParsersAction[StateCliArgumentParser],
    ) -> None:
        delegation = domains.add_parser("delegation")
        commands = delegation.add_subparsers(dest="delegation_command", required=True)
        assign = commands.add_parser("assign")
        self._delegation_identity_arguments(assign)
        assign.add_argument("--target-actor-id", required=True)
        assign.add_argument("--assignment", required=True)
        assign.add_argument(
            "--topology-policy",
            choices=tuple(policy.value for policy in DelegationTopologyPolicy),
            default=DelegationTopologyPolicy.UNSPECIFIED.value,
        )
        assign.set_defaults(operation=StateCliOperation.DELEGATION_ASSIGN)

        report = commands.add_parser("report")
        self._delegation_identity_arguments(report)
        report.add_argument("--verdict", required=True)
        report.add_argument("--summary", required=True)
        report.add_argument("--outcome-ref", required=True)
        report.add_argument("--blocking-finding", action="append", dest="blocking_findings")
        report.set_defaults(
            operation=StateCliOperation.DELEGATION_REPORT,
            blocking_findings=[],
        )

        consume = commands.add_parser("consume")
        self._delegation_identity_arguments(consume)
        consume.set_defaults(operation=StateCliOperation.DELEGATION_CONSUME)

    def _delegation_identity_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--delegation-id", required=True)
        parser.add_argument("--idempotency-key", required=True)

    def _enclave_parser(
        self,
        domains: argparse._SubParsersAction[StateCliArgumentParser],
    ) -> None:
        enclave = domains.add_parser("enclave")
        commands = enclave.add_subparsers(dest="enclave_command", required=True)
        show = commands.add_parser("show")
        show.set_defaults(operation=StateCliOperation.ENCLAVE_SHOW)
        set_command = commands.add_parser("set")
        set_command.add_argument("--key", required=True)
        set_command.add_argument("--value", required=True)
        set_command.add_argument(
            "--source-kind",
            choices=tuple(source.value for source in EnclaveSourceKind),
            required=True,
        )
        set_command.add_argument("--source-turn-id", required=True)
        set_command.set_defaults(operation=StateCliOperation.ENCLAVE_SET)
        delete = commands.add_parser("delete")
        delete.add_argument("--key", required=True)
        delete.set_defaults(operation=StateCliOperation.ENCLAVE_DELETE)

    def _worktree_parser(
        self,
        domains: argparse._SubParsersAction[StateCliArgumentParser],
    ) -> None:
        worktree = domains.add_parser("worktree")
        commands = worktree.add_subparsers(dest="worktree_command", required=True)
        claim = commands.add_parser("claim")
        claim.set_defaults(operation=StateCliOperation.WORKTREE_CLAIM)
        release = commands.add_parser("release")
        release.set_defaults(operation=StateCliOperation.WORKTREE_RELEASE)


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    cli_result = StateCliApplication().run(tuple(sys.argv[1:]), os.environ, Path.cwd())
    sys.stdout.write(f"{cli_result.stdout}\n")
    raise SystemExit(cli_result.exit_code)

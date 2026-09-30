"""Adaptive executable evidence를 현재 worktree의 실제 pytest 실행에 결속합니다."""

import re
import shlex
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass

from scripts.agent_harness.adaptive_control import (
    AuthorityReceipt,
    CriterionEvidence,
    EvidenceAuthority,
    EvidenceKind,
    EvidenceStatus,
    GoalContract,
)
from scripts.agent_harness.adaptive_control_store import (
    AdaptiveControlState,
    InvalidAdaptiveControlState,
)
from scripts.agent_harness.artifact_store import ArtifactStoreError, SessionArtifactStore
from scripts.agent_harness.harness_incident import (
    HarnessIncidentValidationError,
    resolve_neurath_import_provenance,
    run_regression_commands,
    source_checkout_import_roots,
)
from scripts.agent_harness.repository_readback import (
    RepositoryReadbackError,
    RepositoryWorktreeReadback,
)
from scripts.agent_harness.session_kernel import (
    ActorStatus,
    SessionStatus,
    WorkflowId,
    WorkflowRecord,
    WorkflowStatus,
)
from scripts.agent_harness.state_handle import StateHandle


class AdaptiveExecutionReceiptError(RuntimeError):
    """Adaptive runtime execution receipt를 발행하거나 검증할 수 없음을 나타냅니다."""


class AdaptiveExecutionReceiptAuthorityError(AdaptiveExecutionReceiptError):
    """Current actor가 exact workflow execution authority를 갖지 않음을 나타냅니다."""


class AdaptiveExecutionReceiptConflict(AdaptiveExecutionReceiptError):
    """Execution 전후 workflow 또는 worktree bytes가 변했음을 나타냅니다."""


class AdaptiveExecutionReceiptInvalid(AdaptiveExecutionReceiptError):
    """Node, artifact, lineage 또는 replay result가 receipt contract와 다름을 나타냅니다."""


@dataclass(frozen=True, slots=True)
class AdaptiveExecutionReceiptIssuance:
    """Harness가 실행한 criterion evidence와 실행 시점 identity입니다."""

    evidence: CriterionEvidence
    """실제 pytest PASS artifact를 가리키는 executable criterion evidence입니다."""

    workflow_revision: int
    """Execution admission과 artifact 발행이 공유한 workflow-local revision입니다."""

    worktree_fingerprint: str
    """Pytest 실행 전후 동일함을 확인한 current worktree bytes identity입니다."""

    pytest_node: str
    """Harness가 실제 실행하고 artifact에 고정한 exact collectable pytest node입니다."""


class AdaptiveExecutionReceiptStore:
    """Exact pytest node execution과 content-addressed runtime replay를 결합합니다."""

    _ARTIFACT_SCHEMA = "neurath.adaptive-execution-receipt.v2"
    _ISSUER_ID = "harness:adaptive-execution"
    _EXECUTABLE_KINDS = frozenset({
        EvidenceKind.EXAMPLE_TEST,
        EvidenceKind.PROPERTY_TEST,
        EvidenceKind.METAMORPHIC_TEST,
        EvidenceKind.MUTATION_TEST,
    })
    _ARTIFACT_FIELDS = frozenset({
        "command_argv",
        "command_receipt",
        "criterion_id",
        "evidence_kind",
        "goal_fingerprint",
        "intent_revision",
        "owner_actor_id",
        "pytest_node",
        "schema",
        "session_id",
        "source_import_provenance",
        "source_import_roots",
        "source_revision",
        "workflow_id",
        "workflow_revision",
        "worktree_fingerprint",
    })
    _COMMAND_RECEIPT_FIELDS = frozenset({
        "command",
        "exit_code",
        "head_sha",
        "output_sha256",
        "verified_at",
    })

    def __init__(self, handle: StateHandle, workflow_id: WorkflowId) -> None:
        """Runtime identity, workflow, repository root와 per-readback replay cache를 고정합니다.

        Args:
            handle: Session, actor, repository control root가 검증된 runtime facade입니다.
            workflow_id: Executable evidence를 소유하는 exact active workflow입니다.
        """
        self._handle = handle
        self._workflow_id = workflow_id
        self._artifacts = SessionArtifactStore(handle)
        self._repository = RepositoryWorktreeReadback(handle._repository_control_root())
        self._verified: set[tuple[str, str, int]] = set()

    def execute_pytest(
        self,
        contract: GoalContract,
        *,
        criterion_id: str,
        evidence_kind: EvidenceKind,
        pytest_node: str,
    ) -> AdaptiveExecutionReceiptIssuance:
        """Current owner가 exact tracked pytest node를 실행하고 PASS receipt를 발행합니다.

        Args:
            contract: Criterion과 source identity를 고정하는 current goal contract입니다.
            criterion_id: Executable PASS가 증명해야 하는 declared criterion입니다.
            evidence_kind: 해당 criterion이 허용한 executable evidence surface입니다.
            pytest_node: Repository에서 추적되는 exact pytest node selector입니다.

        Returns:
            실제 실행 evidence와 발행 시점 workflow/worktree identity입니다.

        Raises:
            AdaptiveExecutionReceiptAuthorityError: Current actor가 workflow owner가 아니거나
                workflow가 active가 아니면 발생합니다.
            AdaptiveExecutionReceiptInvalid: Contract, node, 실행 결과 또는 artifact가 receipt
                계약을 만족하지 않으면 발생합니다.
            AdaptiveExecutionReceiptConflict: 실행 중 workflow나 worktree bytes가 바뀌면
                발생합니다.
            RepositoryReadbackError: Current worktree fingerprint 또는 tracked node를 읽을 수
                없으면 발생합니다.
        """
        workflow = self._active_owner_workflow()
        self._require_contract(workflow, contract, criterion_id, evidence_kind)
        normalized_node = self._pytest_node(pytest_node)
        command_argv = self._command_argv(normalized_node)
        command = shlex.join(command_argv)
        source_import_provenance = self._source_import_provenance(normalized_node)
        source_import_roots = self._source_import_roots()
        before_fingerprint = self._repository.worktree_fingerprint()
        self._repository.read_tracked_file(normalized_node.split("::", maxsplit=1)[0])
        try:
            receipts = run_regression_commands(
                self._handle._repository_control_root(),
                [command],
            )
        except HarnessIncidentValidationError as error:
            raise AdaptiveExecutionReceiptInvalid(str(error)) from error
        after_fingerprint = self._repository.worktree_fingerprint()
        if after_fingerprint != before_fingerprint:
            raise AdaptiveExecutionReceiptConflict(
                "pytest execution changed current worktree bytes"
            )
        latest = self._active_owner_workflow()
        if latest.revision != workflow.revision or latest.payload != workflow.payload:
            raise AdaptiveExecutionReceiptConflict(
                "workflow changed while issuing adaptive execution receipt"
            )
        if len(receipts) != 1:
            raise AdaptiveExecutionReceiptInvalid(
                "adaptive execution must produce exactly one command receipt"
            )
        command_receipt = receipts[0]
        artifact = {
            "command_argv": list(command_argv),
            "command_receipt": command_receipt,
            "criterion_id": criterion_id,
            "evidence_kind": evidence_kind.value,
            "goal_fingerprint": contract.fingerprint,
            "intent_revision": contract.intent_revision,
            "owner_actor_id": str(workflow.owner_actor_id),
            "pytest_node": normalized_node,
            "schema": self._ARTIFACT_SCHEMA,
            "session_id": str(self._handle.session_id),
            "source_import_provenance": source_import_provenance,
            "source_import_roots": list(source_import_roots),
            "source_revision": contract.source_revision,
            "workflow_id": str(self._workflow_id),
            "workflow_revision": workflow.revision,
            "worktree_fingerprint": after_fingerprint,
        }
        try:
            receipt = self._artifacts.put_json(artifact)
        except ArtifactStoreError as error:
            raise AdaptiveExecutionReceiptInvalid(str(error)) from error
        lineage = AuthorityReceipt(
            authority=EvidenceAuthority.EXECUTABLE,
            issuer_id=self._ISSUER_ID,
            subject_id=str(workflow.owner_actor_id),
            intent_revision=contract.intent_revision,
            source_revision=contract.source_revision,
            receipt_digest=receipt.reference.removeprefix("sha256:"),
        )
        evidence = CriterionEvidence(
            goal_fingerprint=contract.fingerprint,
            criterion_id=criterion_id,
            kind=evidence_kind,
            authority=EvidenceAuthority.EXECUTABLE,
            status=EvidenceStatus.PASS,
            reference=receipt.reference,
            lineage=lineage,
        )
        return AdaptiveExecutionReceiptIssuance(
            evidence=evidence,
            workflow_revision=workflow.revision,
            worktree_fingerprint=after_fingerprint,
            pytest_node=normalized_node,
        )

    def verify(
        self,
        evidence: CriterionEvidence,
        contract: GoalContract,
        *,
        expected_workflow_revision: int,
    ) -> None:
        """Persisted receipt를 current dirty bytes에서 exact node replay로 재검증합니다.

        Args:
            evidence: Content-addressed execution artifact를 가리키는 persisted evidence입니다.
            contract: Evidence가 증명해야 하는 current goal과 criterion 계약입니다.
            expected_workflow_revision: Candidate 평가가 고정한 workflow-local revision입니다.

        Raises:
            AdaptiveExecutionReceiptAuthorityError: Current actor가 exact active workflow를
                소유하지 않으면 발생합니다.
            AdaptiveExecutionReceiptInvalid: Evidence, artifact, revision 또는 replay 결과가
                current contract와 다르면 발생합니다.
            AdaptiveExecutionReceiptConflict: Replay가 current worktree bytes를 바꾸면
                발생합니다.
            RepositoryReadbackError: Current worktree fingerprint를 읽을 수 없으면 발생합니다.
        """
        workflow = self._active_owner_workflow()
        self._require_contract(workflow, contract, evidence.criterion_id, evidence.kind)
        self._require_evidence(evidence, contract)
        if (
            not isinstance(expected_workflow_revision, int)
            or isinstance(expected_workflow_revision, bool)
            or expected_workflow_revision < 0
        ):
            raise AdaptiveExecutionReceiptInvalid(
                "expected execution workflow revision must be non-negative"
            )
        try:
            artifact = self._artifacts.read_json(evidence.reference)
        except ArtifactStoreError as error:
            raise AdaptiveExecutionReceiptInvalid(str(error)) from error
        self._verify_artifact(
            artifact,
            evidence,
            contract,
            workflow,
            expected_workflow_revision,
        )
        current_fingerprint = self._repository.worktree_fingerprint()
        if artifact.get("worktree_fingerprint") != current_fingerprint:
            raise AdaptiveExecutionReceiptInvalid(
                "adaptive execution receipt belongs to stale worktree bytes"
            )
        cache_key = (
            evidence.reference,
            current_fingerprint,
            expected_workflow_revision,
        )
        if cache_key in self._verified:
            return
        pytest_node = artifact.get("pytest_node")
        if not isinstance(pytest_node, str):
            raise AdaptiveExecutionReceiptInvalid("adaptive execution pytest node is invalid")
        normalized_node = self._pytest_node(pytest_node)
        command = shlex.join(self._command_argv(normalized_node))
        try:
            replay = run_regression_commands(
                self._handle._repository_control_root(),
                [command],
            )
        except HarnessIncidentValidationError as error:
            raise AdaptiveExecutionReceiptInvalid(str(error)) from error
        after_fingerprint = self._repository.worktree_fingerprint()
        if after_fingerprint != current_fingerprint:
            raise AdaptiveExecutionReceiptConflict("pytest replay changed current worktree bytes")
        if len(replay) != 1:
            raise AdaptiveExecutionReceiptInvalid(
                "adaptive execution replay must produce exactly one receipt"
            )
        self._verified.add(cache_key)

    def verify_recorded_after_cleanup(
        self, evidence: CriterionEvidence, contract: GoalContract, *,
        expected_workflow_revision: int, root_head_oid: str,
    ) -> None:
        """Verify an immutable prior execution without replaying deleted source.

        This path is used only by issuer-fenced post-cleanup finalization. The
        consumed evaluator candidate must independently preserve the exact
        pre-cleanup payload; this check retains receipt identity, an exit-zero
        command and ancestry to the cleaned primary head. It never substitutes
        the surviving primary checkout's bytes for the deleted worker's bytes.
        """
        workflow = self._active_owner_workflow()
        self._require_contract(workflow, contract, evidence.criterion_id, evidence.kind)
        self._require_evidence(evidence, contract)
        if not isinstance(expected_workflow_revision, int) or isinstance(expected_workflow_revision, bool):
            raise AdaptiveExecutionReceiptInvalid("historical execution revision is invalid")
        try:
            artifact = self._artifacts.read_json(evidence.reference)
        except ArtifactStoreError as error:
            raise AdaptiveExecutionReceiptInvalid(str(error)) from error
        if not isinstance(artifact, Mapping) or frozenset(artifact) != self._ARTIFACT_FIELDS:
            raise AdaptiveExecutionReceiptInvalid("historical execution artifact schema changed")
        node = artifact.get("pytest_node")
        if (not isinstance(node, str) or not node or node != node.strip()
                or "\0" in node or "\\" in node or node.startswith(("-", "/"))
                or ".." in node.split("::", 1)[0].split("/")
                or len(node.split("::")) < 2 or not node.split("::", 1)[0].endswith(".py")):
            raise AdaptiveExecutionReceiptInvalid("historical pytest node is invalid")
        command_argv = self._command_argv(node)
        expected = {
            "command_argv": list(command_argv),
            "criterion_id": evidence.criterion_id,
            "evidence_kind": evidence.kind.value,
            "goal_fingerprint": contract.fingerprint,
            "intent_revision": contract.intent_revision,
            "owner_actor_id": str(workflow.owner_actor_id),
            "schema": self._ARTIFACT_SCHEMA,
            "session_id": str(self._handle.session_id),
            "source_revision": contract.source_revision,
            "workflow_id": str(self._workflow_id),
            "workflow_revision": expected_workflow_revision,
        }
        if any(artifact.get(key) != value for key, value in expected.items()):
            raise AdaptiveExecutionReceiptInvalid("historical execution artifact identity changed")
        self._verify_command_receipt(artifact.get("command_receipt"), command_argv)
        fingerprint = artifact.get("worktree_fingerprint")
        if not self._sha(fingerprint, 64):
            raise AdaptiveExecutionReceiptInvalid("historical worktree fingerprint is invalid")
        provenance = artifact.get("source_import_provenance")
        if (not isinstance(provenance, Mapping) or provenance.get("module") != "neurath"
                or not isinstance(provenance.get("resolved_origin"), str)
                or not provenance["resolved_origin"]
                or not isinstance(artifact.get("source_import_roots"), list)
                or not artifact["source_import_roots"]):
            raise AdaptiveExecutionReceiptInvalid("historical import provenance is invalid")
        receipt = artifact["command_receipt"]
        if not self._sha(root_head_oid, 40):
            raise AdaptiveExecutionReceiptInvalid("cleaned primary head is invalid")
        ancestor = subprocess.run(
            ["git", "-C", str(self._handle._repository_control_root()), "merge-base",
             "--is-ancestor", receipt["head_sha"], root_head_oid],
            check=False, capture_output=True,
        )
        if ancestor.returncode != 0:
            raise AdaptiveExecutionReceiptInvalid("historical execution is not in the cleaned primary head")

    def _active_owner_workflow(self) -> WorkflowRecord:
        state = self._handle.inspect()
        if state.session.status is not SessionStatus.ACTIVE:
            raise AdaptiveExecutionReceiptAuthorityError("execution session is not active")
        actor = state.actors.get(self._handle.actor_id)
        if actor is None or actor.status is not ActorStatus.ACTIVE:
            raise AdaptiveExecutionReceiptAuthorityError("execution owner actor is not active")
        workflow = state.workflows.get(self._workflow_id)
        if workflow is None or workflow.status is not WorkflowStatus.ACTIVE:
            raise AdaptiveExecutionReceiptAuthorityError("execution workflow is not active")
        if workflow.owner_actor_id != self._handle.actor_id:
            raise AdaptiveExecutionReceiptAuthorityError(
                "only the active workflow owner can issue executable evidence"
            )
        return workflow

    def _require_contract(
        self,
        workflow: WorkflowRecord,
        contract: GoalContract,
        criterion_id: str,
        evidence_kind: EvidenceKind,
    ) -> None:
        skill_state = workflow.payload.get("skill_state")
        if not isinstance(skill_state, Mapping):
            raise AdaptiveExecutionReceiptInvalid(
                "adaptive execution workflow skill_state must be an object"
            )
        raw_current = skill_state.get("adaptive_control")
        if raw_current is None:
            if workflow.goal != contract.goal:
                raise AdaptiveExecutionReceiptInvalid(
                    "adaptive execution goal does not match its initial workflow goal"
                )
        else:
            if not isinstance(raw_current, Mapping):
                raise AdaptiveExecutionReceiptInvalid(
                    "adaptive execution current state must be an object"
                )
            try:
                current = AdaptiveControlState.from_payload(raw_current)
            except InvalidAdaptiveControlState as error:
                raise AdaptiveExecutionReceiptInvalid(
                    "adaptive execution current state is invalid"
                ) from error
            if current.contract != contract:
                raise AdaptiveExecutionReceiptInvalid(
                    "adaptive execution contract is not the current typed contract"
                )
        if evidence_kind not in self._EXECUTABLE_KINDS:
            raise AdaptiveExecutionReceiptInvalid(
                "adaptive execution evidence kind is not executable"
            )
        criterion = next(
            (item for item in contract.criteria if item.criterion_id == criterion_id),
            None,
        )
        if criterion is None or evidence_kind not in criterion.required_evidence:
            raise AdaptiveExecutionReceiptInvalid(
                "adaptive execution criterion does not declare this evidence kind"
            )

    def _require_evidence(
        self,
        evidence: CriterionEvidence,
        contract: GoalContract,
    ) -> None:
        lineage = evidence.lineage
        if (
            evidence.status is not EvidenceStatus.PASS
            or evidence.authority is not EvidenceAuthority.EXECUTABLE
            or evidence.goal_fingerprint != contract.fingerprint
            or lineage.authority is not EvidenceAuthority.EXECUTABLE
            or lineage.issuer_id != self._ISSUER_ID
            or lineage.subject_id != str(self._handle.actor_id)
            or not lineage.is_current(contract.intent_revision, contract.source_revision)
            or evidence.reference != f"sha256:{lineage.receipt_digest}"
        ):
            raise AdaptiveExecutionReceiptInvalid(
                "adaptive executable evidence lineage is stale or foreign"
            )

    def _verify_artifact(
        self,
        artifact: Mapping[str, object],
        evidence: CriterionEvidence,
        contract: GoalContract,
        workflow: WorkflowRecord,
        expected_workflow_revision: int,
    ) -> None:
        if frozenset(artifact) != self._ARTIFACT_FIELDS:
            raise AdaptiveExecutionReceiptInvalid(
                "adaptive execution artifact fields do not match its schema"
            )
        pytest_node = artifact.get("pytest_node")
        if not isinstance(pytest_node, str):
            raise AdaptiveExecutionReceiptInvalid("adaptive execution pytest node is invalid")
        command_argv = self._command_argv(self._pytest_node(pytest_node))
        expected = {
            "command_argv": list(command_argv),
            "criterion_id": evidence.criterion_id,
            "evidence_kind": evidence.kind.value,
            "goal_fingerprint": contract.fingerprint,
            "intent_revision": contract.intent_revision,
            "owner_actor_id": str(workflow.owner_actor_id),
            "pytest_node": pytest_node,
            "schema": self._ARTIFACT_SCHEMA,
            "session_id": str(self._handle.session_id),
            "source_import_provenance": self._source_import_provenance(pytest_node),
            "source_import_roots": list(self._source_import_roots()),
            "source_revision": contract.source_revision,
            "workflow_id": str(self._workflow_id),
            "workflow_revision": expected_workflow_revision,
        }
        if any(artifact.get(key) != value for key, value in expected.items()):
            raise AdaptiveExecutionReceiptInvalid(
                "adaptive execution artifact identity is stale or foreign"
            )
        self._verify_command_receipt(artifact.get("command_receipt"), command_argv)
        fingerprint = artifact.get("worktree_fingerprint")
        if not isinstance(fingerprint, str) or re.fullmatch(r"[0-9a-f]{64}", fingerprint) is None:
            raise AdaptiveExecutionReceiptInvalid(
                "adaptive execution worktree fingerprint is invalid"
            )

    def _verify_command_receipt(
        self,
        value: object,
        command_argv: tuple[str, ...],
    ) -> None:
        if not isinstance(value, Mapping) or frozenset(value) != self._COMMAND_RECEIPT_FIELDS:
            raise AdaptiveExecutionReceiptInvalid(
                "adaptive execution command receipt fields are invalid"
            )
        command = value.get("command")
        if (
            command != shlex.join(command_argv)
            or value.get("exit_code") != 0
            or not self._sha(value.get("head_sha"), 40)
            or not self._sha(value.get("output_sha256"), 64)
            or not isinstance(value.get("verified_at"), str)
            or not str(value.get("verified_at")).strip()
        ):
            raise AdaptiveExecutionReceiptInvalid(
                "adaptive execution command receipt does not prove exact exit-zero execution"
            )

    def _pytest_node(self, value: str) -> str:
        if (
            not isinstance(value, str)
            or not value
            or value != value.strip()
            or "\0" in value
            or "\\" in value
            or value.startswith("-")
        ):
            raise AdaptiveExecutionReceiptInvalid(
                "pytest node must be one canonical shell-free argument"
            )
        parts = value.split("::")
        if len(parts) < 2 or any(not part for part in parts) or not parts[0].endswith(".py"):
            raise AdaptiveExecutionReceiptInvalid(
                "pytest node must select a tracked test inside a Python file"
            )
        try:
            self._repository.read_tracked_file(parts[0])
        except RepositoryReadbackError as error:
            raise AdaptiveExecutionReceiptInvalid(str(error)) from error
        return value

    def _command_argv(self, pytest_node: str) -> tuple[str, ...]:
        return (".neurath/run", "verify", "pytest", "--node", pytest_node)

    def _source_import_roots(self) -> tuple[str, ...]:
        root = self._handle._repository_control_root().resolve()
        return tuple(
            "." if path == root else path.relative_to(root).as_posix()
            for path in source_checkout_import_roots(root)
        )

    def _source_import_provenance(self, pytest_node: str) -> dict[str, str | None]:
        try:
            return resolve_neurath_import_provenance(
                self._handle._repository_control_root(),
                pytest_node,
            )
        except HarnessIncidentValidationError as error:
            raise AdaptiveExecutionReceiptInvalid(str(error)) from error

    def _sha(self, value: object, width: int) -> bool:
        return isinstance(value, str) and re.fullmatch(rf"[0-9a-f]{{{width}}}", value) is not None

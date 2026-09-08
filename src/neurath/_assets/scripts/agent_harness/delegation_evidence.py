"""Consumed delegation의 canonical assignment와 immutable artifact를 read-only로 결합합니다."""

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from types import MappingProxyType

from scripts.agent_harness.artifact_store import ArtifactStoreError, SessionArtifactStore
from scripts.agent_harness.session_kernel import (
    ActorId,
    DelegationId,
    DelegationRecord,
    DelegationStatus,
    DelegationTopologyPolicy,
    WorkflowId,
    WorkflowStatus,
)
from scripts.agent_harness.state_handle import StateHandle


class DelegationEvidenceError(RuntimeError):
    """Canonical delegation evidence를 안전하게 읽을 수 없음을 나타냅니다."""


class DelegationEvidenceNotFound(DelegationEvidenceError):
    """Exact workflow와 selector에 해당하는 delegation이 없을 때 발생합니다."""


class DelegationEvidenceConflict(DelegationEvidenceError):
    """Selector 하나에 여러 delegation 또는 non-consumed lifecycle이 걸릴 때 발생합니다."""


class DelegationEvidenceInvalid(DelegationEvidenceError):
    """Assignment, artifact, typed result 사이의 invariant가 깨졌을 때 발생합니다."""


class ImmutableJsonCodec:
    """JSON-compatible object를 deeply immutable snapshot과 detached payload로 변환합니다."""

    def freeze_mapping(self, value: Mapping[str, object]) -> Mapping[str, object]:
        """Nested JSON object를 immutable mapping/tuple tree로 변환합니다.

        Args:
            value: Snapshot에 결속할 string-keyed JSON object입니다.

        Returns:
            Nested collection을 공유하지 않는 read-only mapping입니다.
        """
        return MappingProxyType({key: self._freeze_value(item) for key, item in value.items()})

    def thaw_mapping(self, value: Mapping[str, object]) -> dict[str, object]:
        """Immutable JSON mapping을 detached dict/list tree로 복원합니다.

        Args:
            value: Shared snapshot이 소유하는 immutable mapping입니다.

        Returns:
            Consumer가 snapshot과 독립적으로 변경할 수 있는 JSON object입니다.
        """
        return {key: self.thaw_value(item) for key, item in value.items()}

    def thaw_value(self, value: object) -> object:
        """Immutable JSON value 하나를 detached JSON-compatible value로 복원합니다.

        Args:
            value: Mapping, sequence 또는 scalar JSON value입니다.

        Returns:
            Mapping은 dict, sequence는 list, scalar는 원래 값입니다.
        """
        if isinstance(value, Mapping):
            return {str(key): self.thaw_value(item) for key, item in value.items()}
        if isinstance(value, Sequence) and not isinstance(value, str | bytes):
            return [self.thaw_value(item) for item in value]
        return value

    def _freeze_value(self, value: object) -> object:
        if isinstance(value, Mapping):
            return MappingProxyType({
                str(key): self._freeze_value(item) for key, item in value.items()
            })
        if isinstance(value, list | tuple):
            return tuple(self._freeze_value(item) for item in value)
        return value


class ConsumedDelegationEvidenceSnapshot:
    """한 process revision에서 선택한 consumed delegation의 immutable read model입니다."""

    __slots__ = (
        "assignment",
        "delegation_id",
        "kind",
        "outcome_ref",
        "owner_actor_id",
        "process_revision",
        "report",
        "reviewed_head_sha",
        "skill_state",
        "target_actor_id",
        "workflow_id",
        "workflow_revision",
    )

    def __init__(
        self,
        *,
        process_revision: int,
        workflow_id: WorkflowId,
        workflow_revision: int,
        delegation_id: DelegationId,
        owner_actor_id: ActorId,
        target_actor_id: ActorId,
        kind: str,
        reviewed_head_sha: str | None,
        outcome_ref: str,
        skill_state: Mapping[str, object],
        assignment: Mapping[str, object],
        report: Mapping[str, object],
    ) -> None:
        """Cross-aggregate read 결과를 mutation 불가능한 snapshot으로 고정합니다.

        Args:
            process_revision: Topology와 workflow를 함께 읽은 process revision입니다.
            workflow_id: Evidence가 속한 exact workflow identity입니다.
            workflow_revision: Skill-state 원본을 식별하는 workflow-local revision입니다.
            delegation_id: Consumed result의 exact delegation identity입니다.
            owner_actor_id: Assignment를 발행하고 consume한 workflow owner입니다.
            target_actor_id: Artifact result를 제출한 exact actor입니다.
            kind: Canonical assignment에 기록된 delegation kind입니다.
            reviewed_head_sha: Review assignment가 결속한 optional exact commit입니다.
            outcome_ref: Digest verification을 통과한 artifact reference입니다.
            skill_state: 같은 process snapshot에서 읽은 workflow operational state입니다.
            assignment: Typed record가 보존한 self-contained assignment object입니다.
            report: Outcome reference로 읽고 typed result와 대조한 artifact report입니다.
        """
        object.__setattr__(self, "process_revision", process_revision)
        object.__setattr__(self, "workflow_id", workflow_id)
        object.__setattr__(self, "workflow_revision", workflow_revision)
        object.__setattr__(self, "delegation_id", delegation_id)
        object.__setattr__(self, "owner_actor_id", owner_actor_id)
        object.__setattr__(self, "target_actor_id", target_actor_id)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "reviewed_head_sha", reviewed_head_sha)
        object.__setattr__(self, "outcome_ref", outcome_ref)
        codec = ImmutableJsonCodec()
        object.__setattr__(self, "skill_state", codec.freeze_mapping(skill_state))
        object.__setattr__(self, "assignment", codec.freeze_mapping(assignment))
        object.__setattr__(self, "report", codec.freeze_mapping(report))

    process_revision: int
    """Delegation topology와 workflow projection을 함께 선택한 revision입니다."""

    workflow_id: WorkflowId
    """Read model이 절대 벗어나지 않는 exact workflow identity입니다."""

    workflow_revision: int
    """Snapshot의 skill-state 원본 version입니다."""

    delegation_id: DelegationId
    """Consumed artifact를 소유하는 exact delegation identity입니다."""

    owner_actor_id: ActorId
    """Workflow와 delegation을 함께 소유하는 actor identity입니다."""

    target_actor_id: ActorId
    """Typed result와 artifact를 제출한 exact target actor입니다."""

    kind: str
    """Assignment가 선언한 delegation 종류입니다."""

    reviewed_head_sha: str | None
    """Review delegation이 결속한 optional exact Git head입니다."""

    outcome_ref: str
    """Digest-verified artifact를 가리키는 content reference입니다."""

    skill_state: Mapping[str, object]
    """같은 process snapshot에서 선택한 workflow-local operational state입니다."""

    assignment: Mapping[str, object]
    """Workflow identity를 포함한 immutable self-contained assignment입니다."""

    report: Mapping[str, object]
    """Typed result equality를 통과한 immutable artifact report입니다."""

    def __setattr__(self, name: str, value: object) -> None:
        """생성된 evidence snapshot의 변경을 거부합니다.

        Args:
            name: 변경하려는 attribute 이름입니다.
            value: 새로 대입하려는 값입니다.

        Raises:
            AttributeError: Snapshot은 생성 뒤 immutable입니다.
        """
        raise AttributeError(f"{type(self).__name__} is immutable")

    def skill_state_payload(self) -> dict[str, object]:
        """Legacy-free validator가 소비할 detached JSON skill-state를 반환합니다.

        Returns:
            Nested mapping과 sequence가 JSON object/list로 복원된 detached payload입니다.
        """
        return ImmutableJsonCodec().thaw_mapping(self.skill_state)

    def assignment_payload(self) -> dict[str, object]:
        """Phase gate가 읽을 detached canonical assignment를 반환합니다.

        Returns:
            Snapshot의 immutable 원본과 storage를 공유하지 않는 JSON object입니다.
        """
        return ImmutableJsonCodec().thaw_mapping(self.assignment)

    def report_payload(self) -> dict[str, object]:
        """Phase gate가 읽을 detached digest-verified artifact report를 반환합니다.

        Returns:
            Snapshot의 immutable 원본과 storage를 공유하지 않는 JSON object입니다.
        """
        return ImmutableJsonCodec().thaw_mapping(self.report)


class FinalReviewVerification:
    """Final-local-review publication과 phase gate가 공유하는 bounded verification입니다."""

    __slots__ = (
        "blocking_finding_count",
        "harness_audit_evidence_count",
        "head_sha",
        "matrix_id",
        "outcome_ref",
        "row_count",
        "verdict",
        "verified_rows",
    )

    def __init__(
        self,
        *,
        head_sha: str,
        matrix_id: str,
        outcome_ref: str,
        verified_rows: tuple[str, ...],
        row_count: int,
        blocking_finding_count: int,
        verdict: str,
        harness_audit_evidence_count: int,
    ) -> None:
        """Full artifact에서 검증한 bounded receipt를 생성합니다.

        Args:
            head_sha: Review matrix와 report가 공유하는 exact commit입니다.
            matrix_id: Canonical 14-row matrix digest입니다.
            outcome_ref: 검증된 detailed artifact reference입니다.
            verified_rows: Frozen matrix 순서대로 확인된 row identity입니다.
            row_count: Canonical matrix row 수입니다.
            blocking_finding_count: Artifact에 남은 blocker 수입니다.
            verdict: Target actor가 제출한 review verdict입니다.
            harness_audit_evidence_count: Typed harness audit locator 수입니다.
        """
        object.__setattr__(self, "head_sha", head_sha)
        object.__setattr__(self, "matrix_id", matrix_id)
        object.__setattr__(self, "outcome_ref", outcome_ref)
        object.__setattr__(self, "verified_rows", verified_rows)
        object.__setattr__(self, "row_count", row_count)
        object.__setattr__(self, "blocking_finding_count", blocking_finding_count)
        object.__setattr__(self, "verdict", verdict)
        object.__setattr__(
            self,
            "harness_audit_evidence_count",
            harness_audit_evidence_count,
        )

    head_sha: str
    """Review matrix와 artifact가 공유하는 exact commit입니다."""

    matrix_id: str
    """Canonical review rows와 head를 결속한 digest입니다."""

    outcome_ref: str
    """Detailed review artifact의 digest-verified reference입니다."""

    verified_rows: tuple[str, ...]
    """Frozen matrix 순서로 검증된 row identity입니다."""

    row_count: int
    """Canonical final review matrix의 전체 row 수입니다."""

    blocking_finding_count: int
    """Artifact 검증 뒤 남은 blocking finding 수입니다."""

    verdict: str
    """Typed result와 artifact가 공유하는 final review verdict입니다."""

    harness_audit_evidence_count: int
    """검증된 typed harness audit locator 수입니다."""

    def __setattr__(self, name: str, value: object) -> None:
        """생성된 verification receipt 변경을 거부합니다.

        Args:
            name: 변경하려는 attribute 이름입니다.
            value: 새로 대입하려는 값입니다.

        Raises:
            AttributeError: Receipt는 생성 뒤 immutable입니다.
        """
        raise AttributeError(f"{type(self).__name__} is immutable")

    def to_payload(self) -> dict[str, object]:
        """Phase runner가 저장 없이 평가할 bounded verification object를 반환합니다.

        Returns:
            Matrix coverage, blocker, audit, artifact identity를 담은 detached JSON object입니다.
        """
        return {
            "blocking_finding_count": self.blocking_finding_count,
            "harness_audit_checked": True,
            "harness_audit_evidence_count": self.harness_audit_evidence_count,
            "head_sha": self.head_sha,
            "matrix_id": self.matrix_id,
            "outcome_ref": self.outcome_ref,
            "row_count": self.row_count,
            "verdict": self.verdict,
            "verified_row_count": len(self.verified_rows),
            "verified_rows": list(self.verified_rows),
        }


class ConsumedDelegationEvidenceReader:
    """Exact workflow의 consumed assignment와 digest artifact를 read-only로 결합합니다."""

    _ARTIFACT_SCHEMA = "neurath.delegation-result.v1"
    _COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}\Z")

    def __init__(self, handle: StateHandle, workflow_id: WorkflowId) -> None:
        """Runtime-bound authority와 exact workflow selector를 고정합니다.

        Args:
            handle: Exact session과 current workflow owner actor에 결속된 facade입니다.
            workflow_id: Assignment와 workflow projection이 함께 소유하는 identity입니다.
        """
        self._handle = handle
        self._workflow_id = workflow_id
        self._artifacts = SessionArtifactStore(handle)

    def read(
        self,
        *,
        kind: str,
        reviewed_head_sha: str | None = None,
        delegation_id: str | None = None,
    ) -> ConsumedDelegationEvidenceSnapshot:
        """Selector와 일치하는 unique consumed evidence를 exact session에서 읽습니다.

        Args:
            kind: Assignment에 기록된 exact delegation kind입니다.
            reviewed_head_sha: Review kind를 좁힐 optional full lowercase commit SHA입니다.
            delegation_id: 명시한 consumed review 하나를 선택합니다. 생략하면 unique selector를 요구합니다.

        Returns:
            Workflow projection, assignment, artifact가 결합된 immutable snapshot입니다.

        Raises:
            DelegationEvidenceNotFound: Exact selector에 해당하는 delegation이 없을 때
                발생합니다.
            DelegationEvidenceConflict: Matching lifecycle이 consumed가 아니거나 여러 개면
                발생합니다.
            DelegationEvidenceInvalid: Workflow, assignment, artifact, typed result가 서로
                일치하지 않을 때 발생합니다.
        """
        selected_kind = self._nonblank(kind, "kind")
        if (
            reviewed_head_sha is not None
            and self._COMMIT_PATTERN.fullmatch(reviewed_head_sha) is None
        ):
            raise DelegationEvidenceInvalid("reviewed_head_sha must be a full lowercase commit SHA")
        state = self._handle.inspect()
        workflow = state.workflows.get(self._workflow_id)
        if workflow is None:
            raise DelegationEvidenceNotFound(f"workflow is missing: {self._workflow_id}")
        if workflow.owner_actor_id != self._handle.actor_id:
            raise DelegationEvidenceInvalid("workflow owner does not match current actor")
        if workflow.status is not WorkflowStatus.ACTIVE:
            raise DelegationEvidenceInvalid(f"workflow is terminal: {self._workflow_id}")
        skill_state = workflow.payload.get("skill_state")
        if not isinstance(skill_state, Mapping):
            raise DelegationEvidenceInvalid("workflow payload is missing skill_state")
        self._canonical_json(skill_state, "skill_state")

        selected_id = None if delegation_id is None else DelegationId(
            self._nonblank(delegation_id, "delegation_id")
        )
        if selected_id is not None:
            selected = state.delegations.get(selected_id)
            if selected is None:
                raise DelegationEvidenceNotFound(f"delegation is missing: {selected_id}")
            candidates = (selected,)
        else:
            candidates = tuple(state.delegations.values())

        matches: list[tuple[DelegationRecord, Mapping[str, object]]] = []
        for delegation in candidates:
            if delegation.owner_actor_id != self._handle.actor_id:
                if selected_id is not None:
                    raise DelegationEvidenceInvalid("selected delegation has a different owner")
                continue
            if selected_id is None:
                # Generic/native assignments are not review evidence. Select
                # candidates before applying the strict review-assignment codec.
                try:
                    selector = json.loads(delegation.assignment)
                except json.JSONDecodeError:
                    continue
                if not isinstance(selector, dict) or (
                    selector.get("workflow_id") != str(self._workflow_id)
                    or selector.get("kind") != selected_kind
                    or selector.get("reviewed_head_sha") != reviewed_head_sha
                ):
                    continue
            assignment = self._assignment(delegation)
            if (
                assignment.get("workflow_id") != str(self._workflow_id)
                or assignment.get("kind") != selected_kind
                or assignment.get("reviewed_head_sha") != reviewed_head_sha
            ):
                raise DelegationEvidenceInvalid("selected delegation does not match workflow/kind/head")
            matches.append((delegation, assignment))

        if not matches:
            raise DelegationEvidenceNotFound(
                f"delegation evidence is missing: {self._workflow_id}/{selected_kind}"
            )
        if len(matches) != 1:
            raise DelegationEvidenceConflict("exact workflow selector must resolve one delegation")
        delegation, assignment = matches[0]
        target = state.actors.get(delegation.target_actor_id)
        if delegation.topology_policy is not DelegationTopologyPolicy.DIRECT_CHILD:
            raise DelegationEvidenceInvalid(
                "independent delegation evidence requires persisted DIRECT_CHILD policy"
            )
        if target is None or target.parent_actor_id != delegation.owner_actor_id:
            raise DelegationEvidenceInvalid(
                "delegation target must be a direct child of the workflow owner"
            )
        if delegation.status is not DelegationStatus.CONSUMED:
            raise DelegationEvidenceConflict(
                f"delegation evidence must be consumed: {delegation.id}"
            )
        result = delegation.result
        try:
            artifact = self._artifacts.read_json(result.outcome_ref)
        except ArtifactStoreError as error:
            raise DelegationEvidenceInvalid(str(error)) from error
        report = self._artifact_report(artifact, delegation)
        return ConsumedDelegationEvidenceSnapshot(
            process_revision=state.revision,
            workflow_id=self._workflow_id,
            workflow_revision=workflow.revision,
            delegation_id=delegation.id,
            owner_actor_id=delegation.owner_actor_id,
            target_actor_id=delegation.target_actor_id,
            kind=selected_kind,
            reviewed_head_sha=reviewed_head_sha,
            outcome_ref=result.outcome_ref,
            skill_state=skill_state,
            assignment=assignment,
            report=report,
        )

    def _assignment(self, delegation: DelegationRecord) -> Mapping[str, object]:
        try:
            decoded: object = json.loads(delegation.assignment)
        except json.JSONDecodeError as error:
            raise DelegationEvidenceInvalid(
                f"delegation assignment is not valid JSON: {delegation.id}"
            ) from error
        if not isinstance(decoded, dict):
            raise DelegationEvidenceInvalid(
                f"delegation assignment must be an object: {delegation.id}"
            )
        required = ("kind", "target", "scope", "started_at", "workflow_id")
        if any(not isinstance(decoded.get(field), str) or not decoded[field] for field in required):
            raise DelegationEvidenceInvalid(
                f"delegation assignment identity is incomplete: {delegation.id}"
            )
        self._canonical_json(decoded, "delegation assignment")
        return MappingProxyType({str(key): value for key, value in decoded.items()})

    def _artifact_report(
        self,
        artifact: Mapping[str, object],
        delegation: DelegationRecord,
    ) -> Mapping[str, object]:
        if artifact.get("schema") != self._ARTIFACT_SCHEMA:
            raise DelegationEvidenceInvalid("delegation artifact schema mismatch")
        if artifact.get("delegation_id") != str(delegation.id):
            raise DelegationEvidenceInvalid("delegation artifact identity mismatch")
        if artifact.get("target_agent_id") != str(delegation.target_actor_id):
            raise DelegationEvidenceInvalid("delegation artifact target mismatch")
        report = artifact.get("report")
        if not isinstance(report, Mapping):
            raise DelegationEvidenceInvalid("delegation artifact report must be an object")
        self._canonical_json(report, "delegation artifact report")
        blocking_findings = report.get("blocking_findings")
        if not isinstance(blocking_findings, list) or any(
            not isinstance(item, str) or not item.strip() for item in blocking_findings
        ):
            raise DelegationEvidenceInvalid("delegation artifact blocking findings are invalid")
        result = delegation.result
        if (
            report.get("verdict") != result.verdict
            or report.get("summary") != result.summary
            or blocking_findings != list(result.blocking_findings)
        ):
            raise DelegationEvidenceInvalid("delegation artifact does not match typed result")
        return MappingProxyType({str(key): value for key, value in report.items()})

    def _canonical_json(self, value: Mapping[object, object], label: str) -> str:
        if any(not isinstance(key, str) for key in value):
            raise DelegationEvidenceInvalid(f"{label} keys must be strings")
        try:
            return json.dumps(
                dict(value),
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        except (TypeError, ValueError) as error:
            raise DelegationEvidenceInvalid(f"{label} must be JSON-compatible") from error

    def _nonblank(self, value: object, label: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise DelegationEvidenceInvalid(f"{label} must be non-empty")
        return value.strip()


class FinalReviewEvidencePolicy:
    """Canonical final-local-review matrix와 artifact coverage를 bounded receipt로 검증합니다."""

    _AUDIT_EVIDENCE_PATTERN = re.compile(
        r"^(git_diff|process_state|execution_trajectory):sha256:[0-9a-f]{64}$"
    )
    _REVIEW_ROWS = (
        ("C01", "architecture-boundary", "critical"),
        ("C02", "type-discipline", "warning"),
        ("C03", "yagni", "warning"),
        ("C04", "domain-boundary", "critical"),
        ("C05", "naming", "warning"),
        ("C06", "test-gate", "critical"),
        ("C07", "readability", "warning"),
        ("C08", "api-contract", "warning"),
        ("C09", "persistence", "warning"),
        ("C10", "transaction-integrity", "critical"),
        ("C11", "pattern-consistency", "warning"),
        ("C12", "defensive-helper", "warning"),
        ("C13", "operations-consistency", "warning"),
        ("C14", "spec-completeness", "critical"),
    )

    def __init__(self) -> None:
        """Immutable assignment matrix를 detached canonical JSON과 비교하도록 조립합니다."""
        self._json = ImmutableJsonCodec()

    def verify(
        self,
        snapshot: ConsumedDelegationEvidenceSnapshot,
        *,
        expected_kind: str = "final-local-review",
    ) -> FinalReviewVerification:
        """Consumed evidence가 요청한 kind의 canonical 14-row review인지 검증합니다.

        Args:
            snapshot: Shared reader가 assignment/artifact/result equality까지 확인한 evidence입니다.
            expected_kind: Caller가 현재 workflow에서 요구하는 exact delegation kind입니다.

        Returns:
            Publisher와 phase runner가 저장 없이 공유할 bounded verification입니다.

        Raises:
            DelegationEvidenceInvalid: Kind, matrix, coverage, audit, verdict가 review
                계약과 다르면 발생합니다.
        """
        normalized_kind = expected_kind.strip()
        if not normalized_kind:
            raise DelegationEvidenceInvalid("expected delegation kind must be non-empty")
        if snapshot.kind != normalized_kind:
            raise DelegationEvidenceInvalid(f"delegation kind is not {normalized_kind}")
        head_sha = snapshot.reviewed_head_sha
        if not isinstance(head_sha, str):
            raise DelegationEvidenceInvalid(f"{normalized_kind} exact head is missing")
        expected_matrix = self._matrix(head_sha)
        matrix = snapshot.assignment.get("review_acceptance_matrix")
        if not isinstance(matrix, Mapping) or self._json.thaw_value(matrix) != expected_matrix:
            raise DelegationEvidenceInvalid("review matrix does not match assignment")

        report = snapshot.report
        expected_rows = tuple(row_id for row_id, _category, _severity in self._REVIEW_ROWS)
        verified_rows = report.get("verified_review_rows")
        findings = report.get("review_findings")
        blocking_findings = report.get("blocking_findings")
        if not isinstance(verified_rows, Sequence) or isinstance(verified_rows, str | bytes):
            raise DelegationEvidenceInvalid("review artifact coverage is invalid")
        if tuple(verified_rows) != expected_rows:
            raise DelegationEvidenceInvalid("final-local-review C01-C14 coverage is incomplete")
        if not isinstance(findings, Sequence) or isinstance(findings, str | bytes):
            raise DelegationEvidenceInvalid("review artifact findings are invalid")
        if not isinstance(blocking_findings, Sequence) or isinstance(
            blocking_findings,
            str | bytes,
        ):
            raise DelegationEvidenceInvalid("review artifact blocking findings are invalid")
        if findings or blocking_findings:
            raise DelegationEvidenceInvalid("final-local-review blocking finding remains")
        if report.get("verdict") != "pass":
            raise DelegationEvidenceInvalid("final-local-review verdict is not pass")
        if report.get("matrix_head_sha") != head_sha:
            raise DelegationEvidenceInvalid("review artifact head does not match assignment")
        matrix_id = expected_matrix["matrix_id"]
        if report.get("matrix_id") != matrix_id:
            raise DelegationEvidenceInvalid("review artifact matrix does not match assignment")

        audit = report.get("harness_audit")
        if not isinstance(audit, Mapping) or audit.get("checked") is not True:
            raise DelegationEvidenceInvalid("final-local-review harness audit is incomplete")
        evidence = audit.get("evidence")
        if not isinstance(evidence, Sequence) or isinstance(evidence, str | bytes):
            raise DelegationEvidenceInvalid("review artifact audit evidence is invalid")
        sources: set[str] = set()
        for item in evidence:
            if not isinstance(item, str):
                raise DelegationEvidenceInvalid("review artifact audit evidence is invalid")
            match = self._AUDIT_EVIDENCE_PATTERN.fullmatch(item)
            if match is None:
                raise DelegationEvidenceInvalid("review artifact audit evidence is invalid")
            sources.add(match.group(1))
        if sources != {"git_diff", "process_state", "execution_trajectory"}:
            raise DelegationEvidenceInvalid("final-local-review harness audit is incomplete")

        return FinalReviewVerification(
            head_sha=head_sha,
            matrix_id=str(matrix_id),
            outcome_ref=snapshot.outcome_ref,
            verified_rows=expected_rows,
            row_count=len(expected_rows),
            blocking_finding_count=0,
            verdict="pass",
            harness_audit_evidence_count=len(evidence),
        )

    def _matrix(self, head_sha: str) -> dict[str, object]:
        rows = [
            {"category": category, "row_id": row_id, "severity": severity}
            for row_id, category, severity in self._REVIEW_ROWS
        ]
        identity = json.dumps(
            {"head_sha": head_sha, "rows": rows},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return {
            "frozen": True,
            "head_sha": head_sha,
            "matrix_id": hashlib.sha256(identity.encode()).hexdigest(),
            "row_count": len(rows),
            "rows": rows,
        }

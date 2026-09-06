"""Process-ticket delegation을 SessionKernel과 immutable artifact로 관리합니다."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.agent_harness.artifact_store import ArtifactStoreError, SessionArtifactStore
from scripts.agent_harness.session_kernel import (
    ActorId,
    DelegationAssigned,
    DelegationCancelled,
    DelegationConsumed,
    DelegationId,
    DelegationRecord,
    DelegationReported,
    DelegationResult,
    DelegationStatus,
    DelegationTopologyPolicy,
    SessionId,
    SessionKernelError,
    SessionLocator,
    WorkflowId,
    WorkflowStatus,
)
from scripts.agent_harness.state_handle import (
    RuntimeEnvironmentResolver,
    RuntimeIdentityError,
    StateHandle,
)

REVIEW_KINDS = frozenset({"review-code", "final-local-review"})
REVIEW_ROWS = (
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
HARNESS_AUDIT_EVIDENCE_PATTERN = re.compile(
    r"^(git_diff|process_state|execution_trajectory):sha256:[0-9a-f]{64}$"
)
COMMIT_SHA_PATTERN = re.compile(r"[0-9a-f]{40}\Z")
CANONICAL_KEY_PATTERN = re.compile(r"[A-Z0-9][A-Z0-9._-]{2,127}\Z")
ROOT_CAUSE_KEY_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]{2,127}\Z")


class DelegateStateError(RuntimeError):
    """Delegate CLI contract를 만족할 수 없을 때 발생하는 base error입니다."""


class DelegateClaimConflict(DelegateStateError):
    """Existing delegation result와 새 immutable report가 충돌합니다."""


class DelegateInputError(DelegateStateError):
    """CLI input 또는 structured review payload가 invalid할 때 발생합니다."""


class DelegateStateInvariantError(DelegateStateError):
    """Typed delegation, assignment, artifact가 서로 일치하지 않을 때 발생합니다."""


class DelegateTextPolicy:
    """CLI text와 canonical commit identity를 한 곳에서 검증합니다."""

    def nonblank(self, value: object, label: str) -> str:
        """Object를 공백이 아닌 string으로 검증합니다.

        Args:
            value: CLI boundary에서 받은 untrusted 값입니다.
            label: Invalid message에 사용할 field 이름입니다.

        Returns:
            좌우 공백을 제거한 non-empty string입니다.

        Raises:
            DelegateInputError: 값이 string이 아니거나 공백뿐이면 발생합니다.
        """
        if not isinstance(value, str) or not value.strip():
            raise DelegateInputError(f"{label} must be non-empty")
        return value.strip()

    def commit_sha(self, value: object) -> str | None:
        """Optional reviewed head를 full lowercase commit SHA로 검증합니다.

        Args:
            value: CLI에서 받은 optional reviewed head입니다.

        Returns:
            값이 없으면 `None`, 있으면 validated 40-hex SHA입니다.

        Raises:
            DelegateInputError: 값이 full lowercase commit SHA가 아니면 발생합니다.
        """
        if value is None:
            return None
        if not isinstance(value, str) or COMMIT_SHA_PATTERN.fullmatch(value) is None:
            raise DelegateInputError("reviewed_head_sha must be a full lowercase commit SHA")
        return value


class DelegateAssignmentCodec:
    """Typed delegation assignment string과 process-ticket metadata를 변환합니다."""

    def encode(
        self,
        *,
        kind: str,
        target: str,
        scope: str,
        started_at: str,
        reviewed_head_sha: str | None,
        review_acceptance_matrix: Mapping[str, object] | None,
        workflow_id: WorkflowId,
    ) -> str:
        """Assignment metadata를 canonical JSON string으로 직렬화합니다.

        Args:
            kind: Delegated workflow kind입니다.
            target: Human-readable target label입니다.
            scope: Target actor에게 부여한 bounded scope입니다.
            started_at: Assignment 생성 시각입니다.
            reviewed_head_sha: Review kind가 결속할 optional exact head입니다.
            review_acceptance_matrix: Review kind에 결속한 frozen acceptance matrix입니다.
            workflow_id: Delegation aggregate를 소유하는 exact workflow identity입니다.

        Returns:
            SessionKernel `DelegationRecord.assignment`에 저장할 canonical JSON입니다.
        """
        payload: dict[str, object] = {
            "kind": kind,
            "scope": scope,
            "started_at": started_at,
            "target": target,
            "workflow_id": str(workflow_id),
        }
        if reviewed_head_sha is not None:
            payload["reviewed_head_sha"] = reviewed_head_sha
        if review_acceptance_matrix is not None:
            payload["review_acceptance_matrix"] = dict(review_acceptance_matrix)
        return json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    def decode(self, assignment: str) -> dict[str, object]:
        """Persisted assignment를 validated metadata object로 역직렬화합니다.

        Args:
            assignment: SessionKernel delegation에 저장된 assignment string입니다.

        Returns:
            Required kind, target, scope, started_at을 가진 detached object입니다.

        Raises:
            DelegateStateInvariantError: JSON 또는 required field가 invalid하면 발생합니다.
        """
        try:
            payload: object = json.loads(assignment)
        except json.JSONDecodeError as error:
            raise DelegateStateInvariantError("delegation assignment must be valid JSON") from error
        if not isinstance(payload, dict):
            raise DelegateStateInvariantError("delegation assignment must be an object")
        required = ("kind", "target", "scope", "started_at", "workflow_id")
        if any(not isinstance(payload.get(field), str) or not payload[field] for field in required):
            raise DelegateStateInvariantError("delegation assignment identity is incomplete")
        return {str(key): value for key, value in payload.items()}

    def claim(
        self,
        delegation: DelegationRecord,
        assignment: Mapping[str, object],
        owner_session_id: SessionId,
    ) -> dict[str, object]:
        """Typed delegation과 assignment metadata를 caller-facing claim으로 투영합니다.

        Args:
            delegation: Canonical participants와 lifecycle을 가진 typed record입니다.
            assignment: `decode`로 검증한 process-ticket metadata입니다.
            owner_session_id: Delegation을 소유하는 exact root session identity입니다.

        Returns:
            기존 consumer가 identity와 review matrix를 읽을 bounded claim object입니다.
        """
        claim: dict[str, object] = {
            "delegation_id": str(delegation.id),
            "kind": assignment["kind"],
            "owner_actor_id": str(delegation.owner_actor_id),
            "owner_session_id": str(owner_session_id),
            "scope": assignment["scope"],
            "started_at": assignment["started_at"],
            "target": assignment["target"],
            "target_agent_id": str(delegation.target_actor_id),
            "workflow_id": assignment["workflow_id"],
        }
        reviewed_head_sha = assignment.get("reviewed_head_sha")
        if isinstance(reviewed_head_sha, str):
            claim["reviewed_head_sha"] = reviewed_head_sha
        matrix = assignment.get("review_acceptance_matrix")
        if isinstance(matrix, Mapping):
            claim["review_acceptance_matrix"] = dict(matrix)
        return claim


class DelegateReviewPolicy:
    """Frozen matrix, structured finding, audit, inheritance validation을 캡슐화합니다."""

    def __init__(self, worktree: Path, text_policy: DelegateTextPolicy) -> None:
        """Git ancestry boundary와 shared text validation을 주입합니다.

        Args:
            worktree: Delta review ancestry를 확인할 exact Git worktree입니다.
            text_policy: CLI text normalization policy입니다.
        """
        self._worktree = worktree
        self._text = text_policy

    def matrix(self, kind: str, head_sha: str | None) -> dict[str, object] | None:
        """Review kind를 canonical 14-row exact-head matrix에 결속합니다.

        Args:
            kind: Delegated operation kind입니다.
            head_sha: Review할 optional exact commit입니다.

        Returns:
            Non-review kind는 `None`, review kind는 frozen matrix object입니다.

        Raises:
            DelegateInputError: Review kind에 exact head가 없으면 발생합니다.
        """
        if kind not in REVIEW_KINDS:
            return None
        if head_sha is None:
            raise DelegateInputError("local review delegate requires reviewed_head_sha")
        rows = [
            {"category": category, "row_id": row_id, "severity": severity}
            for row_id, category, severity in REVIEW_ROWS
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

    def report(
        self,
        *,
        assignment: Mapping[str, object],
        args: argparse.Namespace,
        prior_verifications: Sequence[Mapping[str, object]],
    ) -> dict[str, object]:
        """Generic 또는 review result CLI를 canonical artifact report로 검증합니다.

        Args:
            assignment: Typed record에서 decode한 assignment metadata입니다.
            args: Verdict, summary, findings, review evidence CLI input입니다.
            prior_verifications: Consumed delegation artifact에서 복원한 prior receipts입니다.

        Returns:
            Typed result의 bounded fields와 artifact detail을 함께 가진 report입니다.

        Raises:
            DelegateInputError: Verdict와 evidence 조합이 invalid하면 발생합니다.
            DelegateStateInvariantError: Frozen matrix record가 assignment와 다르면 발생합니다.
        """
        verdict = self._text.nonblank(args.verdict, "verdict")
        summary = self._text.nonblank(args.summary, "summary")
        findings = [
            self._text.nonblank(finding, "blocking_finding") for finding in args.blocking_finding
        ]
        kind = self._text.nonblank(assignment.get("kind"), "kind")
        if kind not in REVIEW_KINDS:
            self._validate_generic(verdict, findings)
            return {
                "blocking_findings": findings,
                "summary": summary,
                "verdict": verdict,
            }
        if findings:
            raise DelegateInputError("local review requires structured review finding evidence")
        matrix = self.assignment_matrix(assignment)
        return self._structured_report(
            matrix,
            args,
            verdict,
            summary,
            prior_verifications,
        )

    def verification(
        self,
        report: Mapping[str, object],
        matrix: Mapping[str, object],
    ) -> dict[str, object]:
        """Full review artifact에서 phase gate용 bounded verification receipt를 만듭니다.

        Args:
            report: Digest-verified artifact의 structured review report입니다.
            matrix: Canonical assignment에 frozen된 exact-head matrix입니다.

        Returns:
            Matrix coverage, blocker, audit, note count를 포함한 receipt입니다.

        Raises:
            DelegateStateInvariantError: Report array 또는 audit shape가 invalid하면 발생합니다.
        """
        verified_rows = report.get("verified_review_rows")
        findings = report.get("review_findings")
        notes = report.get("review_notes")
        audit = report.get("harness_audit")
        if not isinstance(verified_rows, list) or not isinstance(findings, list):
            raise DelegateStateInvariantError("review artifact coverage is invalid")
        if not isinstance(notes, list) or not isinstance(audit, Mapping):
            raise DelegateStateInvariantError("review artifact evidence is invalid")
        evidence = audit.get("evidence")
        if not isinstance(evidence, list):
            raise DelegateStateInvariantError("review artifact audit evidence is invalid")
        return {
            "blocking_finding_count": len(findings),
            "harness_audit_checked": audit.get("checked") is True,
            "harness_audit_evidence_count": len(evidence),
            "head_sha": matrix.get("head_sha"),
            "matrix_id": matrix.get("matrix_id"),
            "review_note_count": len(notes),
            "row_count": matrix.get("row_count"),
            "verdict": report.get("verdict"),
            "verified_row_count": len(verified_rows),
            "verified_rows": list(verified_rows),
        }

    def _validate_generic(self, verdict: str, findings: Sequence[str]) -> None:
        if verdict == "pass" and findings:
            raise DelegateInputError("pass delegate result cannot contain blocking findings")
        if verdict == "block" and not findings:
            raise DelegateInputError("block delegate result requires a blocking finding")

    def assignment_matrix(
        self,
        assignment: Mapping[str, object],
    ) -> Mapping[str, object]:
        """Assignment에 내장된 frozen matrix를 canonical policy와 대조합니다.

        Args:
            assignment: Typed delegation에 immutable하게 결속된 metadata입니다.

        Returns:
            Assignment exact head와 rows에 일치하는 frozen matrix입니다.

        Raises:
            DelegateStateInvariantError: Matrix가 없거나 canonical 계산과 다르면 발생합니다.
        """
        matrix = assignment.get("review_acceptance_matrix")
        if not isinstance(matrix, Mapping):
            raise DelegateStateInvariantError("local review requires frozen acceptance matrix")
        expected = self.matrix(
            self._text.nonblank(assignment.get("kind"), "kind"),
            self._text.commit_sha(assignment.get("reviewed_head_sha")),
        )
        if expected is None or dict(matrix) != expected:
            raise DelegateStateInvariantError("review matrix does not match assignment")
        return matrix

    def _structured_report(
        self,
        matrix: Mapping[str, object],
        args: argparse.Namespace,
        verdict: str,
        summary: str,
        prior_verifications: Sequence[Mapping[str, object]],
    ) -> dict[str, object]:
        rows = matrix.get("rows")
        if not isinstance(rows, list):
            raise DelegateStateInvariantError("local review matrix rows are missing")
        expected_row_ids = [
            row.get("row_id")
            for row in rows
            if isinstance(row, Mapping) and isinstance(row.get("row_id"), str)
        ]
        row_ids = set(expected_row_ids)
        reverified = list(dict.fromkeys(args.verified_review_row))
        inherited = list(dict.fromkeys(args.inherited_review_row))
        if set(reverified) & set(inherited):
            raise DelegateInputError("review rows cannot be both reverified and inherited")
        if inherited:
            self._validate_inherited_rows(
                prior_verifications=prior_verifications,
                matrix=matrix,
                reverified=reverified,
                inherited=inherited,
                inherited_from_head=args.inherited_from_head,
            )
            if set(reverified) | set(inherited) != row_ids or len(reverified) + len(
                inherited
            ) != len(expected_row_ids):
                raise DelegateInputError(
                    "local review must cover every frozen matrix row exactly once"
                )
            verified_rows = list(expected_row_ids)
        else:
            verified_rows = reverified
            if verified_rows != expected_row_ids:
                raise DelegateInputError(
                    "local review must verify every frozen matrix row exactly once"
                )
        audit_evidence = self._audit_evidence(args.harness_audit_evidence)
        review_findings = [self._finding(value, row_ids) for value in args.review_finding_json]
        review_notes = [self._note(value, row_ids) for value in args.review_note_json]
        entries = [*review_findings, *review_notes]
        stable_keys = [entry["stable_key"] for entry in entries]
        root_cause_keys = [entry["root_cause_key"] for entry in entries]
        if len(stable_keys) != len(set(stable_keys)):
            raise DelegateInputError("local review finding stable keys must be unique")
        if len(root_cause_keys) != len(set(root_cause_keys)):
            raise DelegateInputError("local review root cause keys must be unique")
        if verdict == "pass" and review_findings:
            raise DelegateInputError("pass local review cannot contain blocking findings")
        if verdict == "block" and not review_findings:
            raise DelegateInputError("block local review requires a structured review finding")
        return {
            "blocking_findings": [finding["summary"] for finding in review_findings],
            "harness_audit": {"checked": True, "evidence": audit_evidence},
            "inherited_from_head": args.inherited_from_head if inherited else None,
            "inherited_review_rows": inherited,
            "matrix_head_sha": matrix.get("head_sha"),
            "matrix_id": matrix.get("matrix_id"),
            "review_findings": review_findings,
            "review_notes": review_notes,
            "reverified_review_rows": reverified,
            "summary": summary,
            "verified_review_rows": verified_rows,
            "verdict": verdict,
        }

    def _validate_inherited_rows(
        self,
        *,
        prior_verifications: Sequence[Mapping[str, object]],
        matrix: Mapping[str, object],
        reverified: list[str],
        inherited: list[str],
        inherited_from_head: object,
    ) -> None:
        if not reverified:
            raise DelegateInputError("delta review must reverify at least one affected row")
        if (
            not isinstance(inherited_from_head, str)
            or COMMIT_SHA_PATTERN.fullmatch(inherited_from_head) is None
        ):
            raise DelegateInputError("inherited rows require the previously verified 40-hex head")
        prior = self._prior_verification(prior_verifications, inherited_from_head)
        prior_rows = prior.get("verified_rows")
        if prior.get("verdict") != "pass" or not isinstance(prior_rows, list):
            raise DelegateInputError("inherited rows require a pass prior verified receipt")
        if not set(inherited) <= set(prior_rows):
            raise DelegateInputError("inherited rows must be covered by the prior verified receipt")
        ancestry = subprocess.run(
            (
                "git",
                "-C",
                str(self._worktree),
                "merge-base",
                "--is-ancestor",
                inherited_from_head,
                str(matrix.get("head_sha")),
            ),
            capture_output=True,
            check=False,
        )
        if ancestry.returncode != 0:
            raise DelegateInputError("inherited head must be an ancestor of the reviewed head")

    def _prior_verification(
        self,
        prior_verifications: Sequence[Mapping[str, object]],
        head_sha: str,
    ) -> Mapping[str, object]:
        matching = [item for item in prior_verifications if item.get("head_sha") == head_sha]
        if not matching:
            raise DelegateInputError("inherited rows require a prior verified review receipt")
        proof_fields = (
            "verdict", "verified_rows", "blocking_finding_count", "matrix_id",
            "harness_audit_checked", "harness_audit_evidence_count",
        )
        first = matching[0]
        if any(
            any(item.get(field) != first.get(field) for field in proof_fields)
            for item in matching[1:]
        ):
            raise DelegateInputError("conflicting prior review receipts require a full review")
        return first

    def _audit_evidence(self, values: Sequence[str]) -> list[str]:
        evidence = list(dict.fromkeys(values))
        sources: set[str] = set()
        for item in evidence:
            match = HARNESS_AUDIT_EVIDENCE_PATTERN.fullmatch(item)
            if match is None:
                raise DelegateInputError(
                    "local review harness audit evidence must be a typed SHA-256 locator"
                )
            sources.add(match.group(1))
        if sources != {"git_diff", "process_state", "execution_trajectory"}:
            raise DelegateInputError(
                "local review must audit git diff, process state, and execution trajectory"
            )
        return evidence

    def _finding(self, value: str, row_ids: set[object]) -> dict[str, str]:
        payload = self._json_object(value, "review finding")
        required = (
            "stable_key",
            "row_id",
            "summary",
            "reproduction_command",
            "expected",
            "actual",
            "impact",
            "root_cause_key",
        )
        parsed = {field: self._text.nonblank(payload.get(field), field) for field in required}
        if CANONICAL_KEY_PATTERN.fullmatch(parsed["stable_key"]) is None:
            raise DelegateInputError("review finding stable_key must be canonical")
        if ROOT_CAUSE_KEY_PATTERN.fullmatch(parsed["root_cause_key"]) is None:
            raise DelegateInputError("review finding root_cause_key must be canonical")
        if parsed["row_id"] not in row_ids:
            raise DelegateInputError("review finding row_id is outside the frozen matrix")
        if parsed["expected"] == parsed["actual"]:
            raise DelegateInputError("review finding expected and actual decisions must differ")
        if any("\n" in parsed[field] for field in ("reproduction_command", "expected", "actual")):
            raise DelegateInputError("review finding reproduction evidence must be single-line")
        return parsed

    def _note(self, value: str, row_ids: set[object]) -> dict[str, str]:
        payload = self._json_object(value, "review note")
        required = (
            "stable_key",
            "row_id",
            "summary",
            "severity",
            "impact",
            "root_cause_key",
            "disposition",
            "evidence_command",
            "expected",
            "actual",
        )
        missing = set(required) - set(payload)
        unexpected = set(payload) - set(required)
        if missing:
            raise DelegateInputError(f"review note fields missing: {','.join(sorted(missing))}")
        if unexpected:
            raise DelegateInputError(
                f"review note fields unexpected: {','.join(sorted(unexpected))}"
            )
        parsed = {field: self._text.nonblank(payload.get(field), field) for field in required}
        if CANONICAL_KEY_PATTERN.fullmatch(parsed["stable_key"]) is None:
            raise DelegateInputError("review note stable_key must be canonical")
        if ROOT_CAUSE_KEY_PATTERN.fullmatch(parsed["root_cause_key"]) is None:
            raise DelegateInputError("review note root_cause_key must be canonical")
        if parsed["row_id"] not in row_ids:
            raise DelegateInputError("review note row_id is outside the frozen matrix")
        if any("\n" in item for item in parsed.values()):
            raise DelegateInputError("review note evidence must be single-line")
        severity = parsed["severity"]
        disposition = parsed["disposition"]
        if severity == "warning":
            if disposition != "gap-triage" or parsed["expected"] == parsed["actual"]:
                raise DelegateInputError(
                    "warning review note requires gap-triage with observed risk"
                )
        elif severity == "resolved":
            if disposition not in {"rebutted", "fixed"} or parsed["expected"] != parsed["actual"]:
                raise DelegateInputError(
                    "resolved review note requires verified rebutted or fixed evidence"
                )
        else:
            raise DelegateInputError("review note severity must be warning or resolved")
        return parsed

    def _json_object(self, value: str, label: str) -> dict[str, object]:
        try:
            payload: object = json.loads(value)
        except json.JSONDecodeError as error:
            raise DelegateInputError(f"{label} must be valid JSON") from error
        if not isinstance(payload, dict):
            raise DelegateInputError(f"{label} must be an object")
        return {str(key): item for key, item in payload.items()}


class DelegateStateService:
    """Self-contained delegation lifecycle과 immutable review artifact를 조정합니다."""

    _ARTIFACT_SCHEMA = "neurath.delegation-result.v1"

    def __init__(
        self,
        *,
        handle: StateHandle,
        workflow_id: WorkflowId,
        worktree: Path,
    ) -> None:
        """Runtime-bound dependencies를 exact workflow service에 고정합니다.

        Args:
            handle: Current actor authority와 exact session을 제공하는 facade입니다.
            workflow_id: Process-ticket operational state를 소유하는 workflow입니다.
            worktree: Git ancestry validation이 사용할 current worktree입니다.
        """
        self._handle = handle
        self._workflow_id = workflow_id
        self._text = DelegateTextPolicy()
        self._codec = DelegateAssignmentCodec()
        self._review = DelegateReviewPolicy(worktree, self._text)
        self._artifacts = SessionArtifactStore(handle)

    def begin(self, args: argparse.Namespace) -> dict[str, object]:
        """Registered target actor에 typed pending assignment를 생성합니다.

        Args:
            args: Kind, target, scope, target actor, optional reviewed head입니다.

        Returns:
            Exact delegation identity와 optional frozen matrix를 포함한 claim입니다.

        Raises:
            DelegateInputError: Target이 current owner이거나 registered actor가 아니면
                발생합니다.
            SessionKernelError: Typed assignment transition이 invalid하면 발생합니다.
        """
        self._require_workflow(owner_required=True)
        kind = self._text.nonblank(args.kind, "kind")
        target = self._text.nonblank(args.target, "target")
        scope = self._text.nonblank(args.scope, "scope")
        target_actor_id = ActorId(self._text.nonblank(args.target_agent_id, "target_agent_id"))
        if target_actor_id == self._handle.actor_id:
            raise DelegateInputError("delegate target actor cannot equal workflow owner")
        state = self._handle.inspect()
        if target_actor_id not in state.actors:
            raise DelegateInputError(f"delegation actor is unavailable: {target_actor_id}")
        reviewed_head_sha = self._text.commit_sha(args.reviewed_head_sha)
        matrix = self._review.matrix(kind, reviewed_head_sha)
        delegation_id = DelegationId(uuid4().hex)
        assignment = self._codec.encode(
            kind=kind,
            target=target,
            scope=scope,
            started_at=datetime.now(UTC).isoformat(),
            reviewed_head_sha=reviewed_head_sha,
            review_acceptance_matrix=matrix,
            workflow_id=self._workflow_id,
        )
        committed = self._handle.apply(
            DelegationAssigned(
                session_id=self._handle.session_id,
                delegation_id=delegation_id,
                owner_actor_id=self._handle.actor_id,
                target_actor_id=target_actor_id,
                assignment=assignment,
                idempotency_key=f"delegation-assigned:{delegation_id}",
                topology_policy=DelegationTopologyPolicy.DIRECT_CHILD,
            )
        )
        delegation = committed.delegations[delegation_id]
        return self._codec.claim(
            delegation,
            self._codec.decode(assignment),
            self._handle.session_id,
        )

    def submit(self, args: argparse.Namespace) -> dict[str, object]:
        """Exact target의 full report artifact와 bounded typed result를 제출합니다.

        Args:
            args: Delegation/target identity, verdict, summary, review evidence입니다.

        Returns:
            Artifact outcome reference를 포함한 reported result receipt입니다.

        Raises:
            DelegateInputError: Target identity 또는 report 조합이 invalid하면 발생합니다.
            DelegateStateInvariantError: Delegation lifecycle이나 artifact가 불일치하면
                발생합니다.
            SessionKernelError: Current actor가 exact target이 아니면 발생합니다.
        """
        self._require_workflow(owner_required=False)
        delegation_id = DelegationId(self._text.nonblank(args.delegation_id, "delegation_id"))
        target_actor_id = ActorId(self._text.nonblank(args.target_agent_id, "target_agent_id"))
        delegation = self._delegation(delegation_id)
        if (
            target_actor_id != delegation.target_actor_id
            or self._handle.actor_id != target_actor_id
        ):
            raise DelegateInputError("delegation target actor identity mismatch")
        if delegation.status not in {DelegationStatus.PENDING, DelegationStatus.REPORTED}:
            raise DelegateStateInvariantError(f"delegation cannot report: {delegation.status}")
        assignment = self._codec.decode(delegation.assignment)
        kind = self._text.nonblank(assignment.get("kind"), "kind")
        prior_verifications = (
            self._prior_review_verifications()
            if kind in REVIEW_KINDS and args.inherited_review_row
            else ()
        )
        report = self._review.report(
            assignment=assignment,
            args=args,
            prior_verifications=prior_verifications,
        )
        artifact_payload = {
            "delegation_id": str(delegation_id),
            "report": report,
            "schema": self._ARTIFACT_SCHEMA,
            "target_agent_id": str(target_actor_id),
        }
        predicted_reference = self._artifact_reference(artifact_payload)
        if (
            delegation.status is DelegationStatus.REPORTED
            and delegation.result.outcome_ref != predicted_reference
        ):
            raise DelegateClaimConflict(f"delegation result is already reported: {delegation_id}")
        receipt = self._artifacts.put_json(artifact_payload)
        report_findings = report.get("blocking_findings")
        if not isinstance(report_findings, list):
            raise DelegateStateInvariantError("delegation report blocking findings are invalid")
        result = DelegationResult(
            verdict=self._text.nonblank(report.get("verdict"), "verdict"),
            summary=self._text.nonblank(report.get("summary"), "summary"),
            outcome_ref=receipt.reference,
            blocking_findings=tuple(
                self._text.nonblank(item, "blocking_finding") for item in report_findings
            ),
        )
        self._handle.apply(
            DelegationReported(
                session_id=self._handle.session_id,
                delegation_id=delegation_id,
                reporter_actor_id=self._handle.actor_id,
                result=result,
                idempotency_key=f"delegation-reported:{delegation_id}:{receipt.reference}",
            )
        )
        return {
            "blocking_findings": list(result.blocking_findings),
            "delegation_id": str(delegation_id),
            "outcome": "reported",
            "outcome_ref": receipt.reference,
            "result_digest": receipt.reference.removeprefix("sha256:"),
            "summary": result.summary,
            "target_agent_id": str(target_actor_id),
            "verdict": result.verdict,
        }

    def complete(self, args: argparse.Namespace) -> dict[str, object]:
        """Owner가 exact artifact를 readback한 뒤 typed result를 consume합니다.

        Args:
            args: Delegation identity, exact target, reported outcome reference입니다.

        Returns:
            Generic 또는 review verification을 포함한 result-applied receipt입니다.

        Raises:
            DelegateInputError: Target 또는 outcome reference가 typed result와 다르면
                발생합니다.
            DelegateStateInvariantError: Artifact detail이 typed result와 다르면 발생합니다.
            SessionKernelError: Current actor가 delegation owner가 아니면 발생합니다.
        """
        self._require_workflow(owner_required=True)
        delegation_id = DelegationId(self._text.nonblank(args.delegation_id, "delegation_id"))
        target_actor_id = ActorId(self._text.nonblank(args.target_agent_id, "target_agent_id"))
        outcome_ref = self._text.nonblank(args.outcome_ref, "outcome_ref")
        delegation = self._delegation(delegation_id)
        if delegation.owner_actor_id != self._handle.actor_id:
            raise DelegateInputError("delegation owner actor identity mismatch")
        if delegation.target_actor_id != target_actor_id:
            raise DelegateInputError("delegation target actor identity mismatch")
        if delegation.status not in {DelegationStatus.REPORTED, DelegationStatus.CONSUMED}:
            raise DelegateStateInvariantError(
                "delegation result must be reported before completion"
            )
        if delegation.result.outcome_ref != outcome_ref:
            raise DelegateInputError("delegation outcome reference mismatch")
        artifact = self._artifacts.read_json(outcome_ref)
        report = self._artifact_report(artifact, delegation)
        assignment = self._codec.decode(delegation.assignment)
        completion = {
            **self._codec.claim(delegation, assignment, self._handle.session_id),
            "outcome": "result-applied",
            "outcome_ref": outcome_ref,
        }
        kind = self._text.nonblank(assignment.get("kind"), "kind")
        if kind in REVIEW_KINDS:
            matrix = self._review.assignment_matrix(assignment)
            completion.update({
                "review_report": report,
                "review_verification": self._review.verification(report, matrix),
                "reviewed_head_sha": assignment.get("reviewed_head_sha"),
            })
        self._handle.apply(
            DelegationConsumed(
                session_id=self._handle.session_id,
                delegation_id=delegation_id,
                consumer_actor_id=self._handle.actor_id,
                idempotency_key=f"delegation-consumed:{delegation_id}:{outcome_ref}",
            )
        )
        return completion

    def abort(self, args: argparse.Namespace) -> dict[str, object]:
        """Owner가 pending delegation을 typed cancellation으로 종료합니다.

        Args:
            args: Delegation identity, exact target, spawn failure reference입니다.

        Returns:
            Review verification을 만들지 않는 spawn-failed completion receipt입니다.

        Raises:
            DelegateInputError: Owner, target 또는 cancellation reference가 invalid하면
                발생합니다.
            SessionKernelError: Delegation이 pending이 아니면 발생합니다.
        """
        self._require_workflow(owner_required=True)
        delegation_id = DelegationId(self._text.nonblank(args.delegation_id, "delegation_id"))
        target_actor_id = ActorId(self._text.nonblank(args.target_agent_id, "target_agent_id"))
        outcome_ref = self._text.nonblank(args.outcome_ref, "outcome_ref")
        delegation = self._delegation(delegation_id)
        if delegation.owner_actor_id != self._handle.actor_id:
            raise DelegateInputError("delegation owner actor identity mismatch")
        if delegation.target_actor_id != target_actor_id:
            raise DelegateInputError("delegation target actor identity mismatch")
        assignment = self._codec.decode(delegation.assignment)
        completion = {
            **self._codec.claim(delegation, assignment, self._handle.session_id),
            "outcome": "spawn-failed",
            "outcome_ref": outcome_ref,
        }
        self._handle.apply(
            DelegationCancelled(
                session_id=self._handle.session_id,
                delegation_id=delegation_id,
                owner_actor_id=self._handle.actor_id,
                reason=outcome_ref,
                idempotency_key=f"delegation-cancelled:{delegation_id}:{outcome_ref}",
            )
        )
        return completion

    def _delegation(self, delegation_id: DelegationId) -> DelegationRecord:
        delegation = self._handle.inspect().delegations.get(delegation_id)
        if delegation is None:
            raise DelegateStateInvariantError(f"delegation is missing: {delegation_id}")
        assignment = self._codec.decode(delegation.assignment)
        if assignment.get("workflow_id") != str(self._workflow_id):
            raise DelegateInputError("delegation workflow identity mismatch")
        return delegation

    def _artifact_reference(self, payload: Mapping[str, object]) -> str:
        try:
            content = json.dumps(
                dict(payload),
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
        except (TypeError, ValueError) as error:
            raise DelegateInputError(
                "delegation result artifact must be JSON serializable"
            ) from error
        return f"sha256:{hashlib.sha256(content).hexdigest()}"

    def _artifact_report(
        self,
        artifact: Mapping[str, object],
        delegation: DelegationRecord,
    ) -> Mapping[str, object]:
        if artifact.get("schema") != self._ARTIFACT_SCHEMA:
            raise DelegateStateInvariantError("delegation artifact schema mismatch")
        if artifact.get("delegation_id") != str(delegation.id):
            raise DelegateStateInvariantError("delegation artifact identity mismatch")
        if artifact.get("target_agent_id") != str(delegation.target_actor_id):
            raise DelegateStateInvariantError("delegation artifact target mismatch")
        report = artifact.get("report")
        if not isinstance(report, Mapping):
            raise DelegateStateInvariantError("delegation artifact report must be an object")
        blocking_findings = report.get("blocking_findings")
        if not isinstance(blocking_findings, list):
            raise DelegateStateInvariantError("delegation artifact blocking findings are invalid")
        expected = {
            "blocking_findings": list(delegation.result.blocking_findings),
            "outcome_ref": delegation.result.outcome_ref,
            "summary": delegation.result.summary,
            "verdict": delegation.result.verdict,
        }
        actual = {
            "blocking_findings": blocking_findings,
            "outcome_ref": self._artifact_reference(artifact),
            "summary": report.get("summary"),
            "verdict": report.get("verdict"),
        }
        if actual != expected:
            raise DelegateStateInvariantError("delegation artifact does not match typed result")
        return report

    def _prior_review_verifications(self) -> tuple[Mapping[str, object], ...]:
        """Consumed review delegations의 immutable proof를 exact session에서 복원합니다.

        Returns:
            Canonical assignment와 digest-verified artifact에서 재구성한 receipts입니다.

        Raises:
            DelegateStateInvariantError: Consumed review proof가 불완전하면 발생합니다.
            ArtifactStoreError: Exact artifact가 없거나 digest 검증에 실패하면 발생합니다.
        """
        verifications: list[Mapping[str, object]] = []
        for delegation in self._handle.inspect().delegations.values():
            if delegation.status is not DelegationStatus.CONSUMED:
                continue
            # Generic state API assignments may be prose or arbitrary JSON.
            # Identify this workflow's review records before strict decoding;
            # unrelated reports never become inherited review evidence.
            try:
                candidate = json.loads(delegation.assignment)
            except json.JSONDecodeError:
                continue
            if not isinstance(candidate, dict):
                continue
            if candidate.get("workflow_id") != str(self._workflow_id):
                continue
            kind = candidate.get("kind")
            if not isinstance(kind, str) or kind not in REVIEW_KINDS:
                continue
            assignment = self._codec.decode(delegation.assignment)
            matrix = self._review.assignment_matrix(assignment)
            artifact = self._artifacts.read_json(delegation.result.outcome_ref)
            report = self._artifact_report(artifact, delegation)
            verifications.append(self._review.verification(report, matrix))
        return tuple(verifications)

    def _require_workflow(self, *, owner_required: bool) -> None:
        """Exact active workflow와 operation별 owner authority를 read-only로 검증합니다.

        Args:
            owner_required: Begin/complete/abort처럼 workflow owner만 가능한 operation인지
                나타냅니다.

        Raises:
            DelegateStateInvariantError: Workflow가 없거나 terminal이면 발생합니다.
            DelegateInputError: Owner operation을 다른 actor가 시도하면 발생합니다.
        """
        workflow = self._handle.inspect().workflows.get(self._workflow_id)
        if workflow is None:
            raise DelegateStateInvariantError(f"workflow is missing: {self._workflow_id}")
        if workflow.status is not WorkflowStatus.ACTIVE:
            raise DelegateStateInvariantError(f"workflow is terminal: {self._workflow_id}")
        if owner_required and workflow.owner_actor_id != self._handle.actor_id:
            raise DelegateInputError("workflow owner actor identity mismatch")


class DelegateStateApplication:
    """CWD/runtime identity에서 exact state service를 조립하는 CLI boundary입니다."""

    def run(self) -> int:
        """CLI input을 parse하고 typed transition 결과를 JSON으로 출력합니다.

        Returns:
            성공은 0, claim conflict는 1, invalid identity/state/input은 2입니다.
        """
        args = self._parser().parse_args()
        try:
            locator = SessionLocator.from_worktree(Path.cwd())
            binding = RuntimeEnvironmentResolver().resolve(os.environ)
            handle = StateHandle.attach(locator, binding)
            service = DelegateStateService(
                handle=handle,
                workflow_id=WorkflowId(args.workflow_id),
                worktree=Path.cwd(),
            )
            if args.command == "begin":
                result = service.begin(args)
            elif args.command == "submit":
                result = service.submit(args)
            elif args.command == "complete":
                result = service.complete(args)
            else:
                result = service.abort(args)
        except DelegateClaimConflict as error:
            print(str(error), file=sys.stderr)
            return 1
        except (
            ArtifactStoreError,
            DelegateStateError,
            OSError,
            RuntimeIdentityError,
            SessionKernelError,
            subprocess.CalledProcessError,
        ) as error:
            print(str(error), file=sys.stderr)
            return 2
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0

    def _parser(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(description="Manage a process-ticket delegation.")
        parser.add_argument("--workflow-id", required=True)
        subparsers = parser.add_subparsers(dest="command", required=True)

        begin = subparsers.add_parser("begin")
        begin.add_argument("--kind", required=True)
        begin.add_argument("--target", required=True)
        begin.add_argument("--scope", required=True)
        begin.add_argument("--target-agent-id", required=True)
        begin.add_argument("--reviewed-head-sha")

        submit = subparsers.add_parser("submit")
        submit.add_argument("--delegation-id", required=True)
        submit.add_argument("--target-agent-id", required=True)
        submit.add_argument("--verdict", choices=("pass", "block", "failed"), required=True)
        submit.add_argument("--summary", required=True)
        submit.add_argument("--blocking-finding", action="append", default=[])
        submit.add_argument("--verified-review-row", action="append", default=[])
        submit.add_argument("--inherited-review-row", action="append", default=[])
        submit.add_argument("--inherited-from-head")
        submit.add_argument("--review-finding-json", action="append", default=[])
        submit.add_argument("--review-note-json", action="append", default=[])
        submit.add_argument("--harness-audit-evidence", action="append", default=[])

        complete = subparsers.add_parser("complete")
        complete.add_argument("--delegation-id", required=True)
        complete.add_argument("--target-agent-id", required=True)
        complete.add_argument("--outcome-ref", required=True)

        abort = subparsers.add_parser("abort")
        abort.add_argument("--delegation-id", required=True)
        abort.add_argument("--target-agent-id", required=True)
        abort.add_argument("--outcome-ref", required=True)
        return parser


if __name__ == "__main__":
    raise SystemExit(DelegateStateApplication().run())

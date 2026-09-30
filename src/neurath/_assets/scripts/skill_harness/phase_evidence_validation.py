"""Semantic evidence validation for contracted phase transitions."""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Mapping
from pathlib import Path

from scripts.agent_harness.adaptive_control import (
    ControlAction,
    EvidenceKind,
    ExecutionStatus,
)
from scripts.agent_harness.adaptive_control_authority import (
    AdaptiveControlAuthorityError,
)
from scripts.agent_harness.adaptive_control_store import (
    AdaptiveControlStoreError,
)
from scripts.agent_harness.delegation_evidence import (
    DelegationEvidenceError,
)
from scripts.agent_harness.evaluation_loop import (
    EVALUATE_HARNESS_MAX_WALL_CLOCK_SECONDS,
)
from scripts.harness_persona_policy import POLICY_ID
from scripts.skill_harness.review_contract import REVIEW_CODE_ROWS
from scripts.skill_harness.harness_source_inventory import HarnessSourceInventory


from scripts.skill_harness.phase_models import (
    PhaseContract,
    PhaseRunState,
    PhaseRunnerError,
    TERMINAL_PHASE_STATUSES,
)
from scripts.skill_harness.phase_store import (
    PhaseRunStore,
    AdaptiveControlPhaseReadback,
    AdaptiveControlTransitionReadback,
)

REVIEW_CODE_ROW_COUNT = len(REVIEW_CODE_ROWS)
REVIEW_CODE_ROW_COUNT_TEXT = str(REVIEW_CODE_ROW_COUNT)


from scripts.skill_harness.phase_repository_evidence import (
    PhaseRepositoryEvidence,
    RegressionNodeOutcome as RegressionNodeOutcome,
)


class PhaseEvidenceValidator:
    """Validate submitted proof against current repository and authority readbacks."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._repository = PhaseRepositoryEvidence(root)

    def evaluate(
        self,
        state: PhaseRunState,
        phase: PhaseContract,
        status: str,
        evidence: tuple[str, ...],
        store: PhaseRunStore,
    ) -> dict[str, object]:
        required_evidence = self.required_evidence(state, phase, status)
        terminal = status in TERMINAL_PHASE_STATUSES
        min_evidence_count = (
            0 if terminal else max(phase.min_evidence_count, len(required_evidence))
        )
        missing_required = [
            required
            for required in required_evidence
            if not any(required in item for item in evidence)
        ]
        if len(evidence) < min_evidence_count or missing_required:
            raise PhaseRunnerError(
                "INSUFFICIENT_EVIDENCE",
                (
                    f"{phase.name} requires at least {min_evidence_count} evidence "
                    f"items and named evidence {list(required_evidence)}"
                ),
            )
        pattern_failures: list[str] = []
        if not terminal:
            clean_skip = (
                state.skill == "finish-session"
                and status == "skipped"
                and phase.name in {"stage_scope", "commit"}
            )
            pattern_failures = [] if clean_skip else self._pattern_failures(phase, evidence)
            pattern_failures.extend(
                self._semantic_failures(
                    state,
                    phase,
                    status,
                    evidence,
                    store.read_skill_state(),
                    store,
                )
            )
        elif state.adaptive_control_required and not (
            status == "blocked" and self.budget_expired(state)
        ):
            pattern_failures.extend(self._adaptive_terminal_transition_failures(status, store))
        if pattern_failures:
            raise PhaseRunnerError(
                "EVIDENCE_PATTERN_MISMATCH",
                f"{phase.name} evidence did not satisfy patterns: {pattern_failures}",
            )
        return {
            "accepted": True,
            "evidence_count": len(evidence),
            "min_evidence_count": min_evidence_count,
            "required_evidence": list(required_evidence),
            "missing_required_evidence": [],
            "pattern_checked_evidence": (
                [] if terminal else sorted((phase.evidence_patterns or {}).keys())
            ),
        }

    def _pattern_failures(
        self,
        phase: PhaseContract,
        evidence: tuple[str, ...],
    ) -> list[str]:
        failures: list[str] = []
        for evidence_key, pattern in (phase.evidence_patterns or {}).items():
            matching_items = [item for item in evidence if evidence_key in item]
            if not matching_items:
                continue
            if not any(re.search(pattern, item, flags=re.IGNORECASE) for item in matching_items):
                failures.append(evidence_key)
        return failures

    def _autopilot_issue_set(
        self,
        evidence: tuple[str, ...],
        label: str,
    ) -> frozenset[int] | None:
        item = self._evidence_item(evidence, label)
        if item is None or ": " not in item:
            return None
        try:
            value = json.loads(item.split(": ", 1)[1])
        except TypeError, ValueError:
            return None
        if not isinstance(value, dict) or set(value) != (
            {"issues", "edges"} if label == "dependency_dag" else {"issues"}
        ):
            return None
        issues = value["issues"]
        if (
            not isinstance(issues, list)
            or any(type(number) is not int or number < 1 for number in issues)
            or len(set(issues)) != len(issues)
        ):
            return None
        if label == "dependency_dag":
            edges = value["edges"]
            if not isinstance(edges, list) or any(
                not isinstance(edge, list)
                or len(edge) != 2
                or any(type(number) is not int or number not in issues for number in edge)
                or edge[0] == edge[1]
                for edge in edges
            ):
                return None
        return frozenset(issues)

    def _semantic_failures(
        self,
        state: PhaseRunState,
        phase: PhaseContract,
        status: str,
        evidence: tuple[str, ...],
        skill_state: Mapping[str, object],
        store: PhaseRunStore,
    ) -> list[str]:
        failures: list[str] = []
        legacy_autopilot = (
            state.skill == "autopilot"
            and hasattr(state, "phases")
            and len(state.phases) == 7
            and state.phases[5].name == "intent_audit_and_docs"
        )
        required_evidence = self.required_evidence(state, phase, status)
        if state.adaptive_control_required and status not in TERMINAL_PHASE_STATUSES:
            failures.extend(self._adaptive_control_transition_failures(state, phase, store))
        if phase.name == "publication" and "local_review_head_sha" in phase.required_evidence:
            failures.extend(self._publication_semantic_failures(evidence))
        elif "push_head_match" in required_evidence:
            failures.extend(self._push_head_match_semantic_failures(evidence))
            previous_commit = self._previous_evidence_item(state, "commit_sha")
            if state.skill == "finish-session" and state.phase(3).status == "skipped":
                previous_commit = self._previous_evidence_item(state, "clean_tree")
            pushed = self._evidence_item(evidence, "push_head_match")
            if previous_commit and self._head_evidence_value(
                previous_commit
            ) != self._head_evidence_value(pushed):
                failures.append("push_head_match.commit_sha_mismatch")
        if phase.name == "monitoring":
            failures.extend(
                self._monitoring_semantic_failures(
                    evidence,
                    skill_state,
                    require_local_review="local_review_head_sha" in phase.required_evidence,
                    require_review_matrix=(
                        "local_review_matrix_receipt" in phase.required_evidence
                    ),
                )
            )
        if phase.name == "merge_cleanup" and status == "completed":
            failures.extend(self._merge_cleanup_semantic_failures(state, evidence))
        if "deterministic_enforcement_gate" in phase.required_evidence:
            failures.extend(self._deterministic_enforcement_failures(evidence))
        if "github_metadata_language" in phase.required_evidence:
            failures.extend(self._github_metadata_language_failures(evidence))
        if "adaptive_control_initialized" in required_evidence:
            failures.extend(self._adaptive_control_initialized_failures(state, evidence, store))
        if "adaptive_control_receipt" in required_evidence:
            failures.extend(self._adaptive_control_receipt_failures(evidence, store))
        if (
            state.skill == "finish-session"
            and status == "skipped"
            and phase.name in {"stage_scope", "commit"}
        ):
            proof = self._evidence_item(evidence, "clean_tree")
            if not re.fullmatch(
                r"clean_tree: head_sha=[0-9a-f]{40} index=clean worktree=clean", proof or ""
            ):
                failures.append("finish_session.clean_tree")
            if phase.name == "commit":
                previous = state.phase(2)
                if previous.status != "skipped":
                    failures.append("finish_session.stage_scope_not_skipped")
                elif self._head_evidence_value(
                    self._evidence_item(previous.evidence, "clean_tree")
                ) != self._head_evidence_value(proof):
                    failures.append("finish_session.clean_tree_head_changed")
        if (
            state.skill == "finish-session"
            and phase.name == "commit"
            and status == "completed"
            and state.phase(2).status != "completed"
        ):
            failures.append("finish_session.stage_scope_not_completed")
        if state.skill == "autopilot" and not legacy_autopilot and phase.name == "collect_issues":
            if self._autopilot_issue_set(evidence, "normalized_items") is None:
                failures.append("autopilot.normalized_items")
        if state.skill == "autopilot" and not legacy_autopilot and phase.name == "dependency_dag":
            collected = self._autopilot_issue_set(state.phase(1).evidence, "normalized_items")
            planned = self._autopilot_issue_set(evidence, "dependency_dag")
            if collected is None or planned is None or collected != planned:
                failures.append("autopilot.dependency_dag_scope")
        if state.skill == "autopilot" and phase.name == "execute_waves":
            wave_id = self._evidence_value(
                self._evidence_item(evidence, "native_wave_receipt"), "wave_id"
            )
            provider_wave_id = self._evidence_value(
                self._evidence_item(evidence, "native_wave_receipt"), "provider_wave_id"
            )
            planned = (
                self._autopilot_issue_set(state.phase(2).evidence, "dependency_dag")
                if not legacy_autopilot and hasattr(state, "phase")
                else None
            )
            no_op = self._evidence_item(evidence, "native_wave_receipt") == (
                "native_wave_receipt: no_op=all_satisfied"
            )
            try:
                if no_op and planned == frozenset():
                    wave = None
                elif provider_wave_id and not wave_id:
                    wave = store.read_provider_wave(provider_wave_id)
                elif provider_wave_id:
                    raise ValueError("wave receipt must select exactly one execution backend")
                else:
                    wave = store.read_native_wave(wave_id) if wave_id else None
                if not (no_op and planned == frozenset()) and (
                    wave is None or wave.get("all_succeeded") is not True
                ):
                    failures.append("native_wave_receipt")
                if not legacy_autopilot and not (no_op and planned == frozenset()):
                    actual = wave.get("states") if wave else None
                    attempts = wave.get("attempts", []) if wave else []
                    predecessors = {item["replacement"]: item["failed"] for item in attempts}

                    def original(identifier):
                        seen = set()
                        while identifier in predecessors and identifier not in seen:
                            seen.add(identifier)
                            identifier = predecessors[identifier]
                        return identifier

                    if (
                        planned is None
                        or not isinstance(actual, Mapping)
                        or {original(identifier) for identifier in actual}
                        != {f"issue-{number}" for number in planned}
                    ):
                        failures.append("autopilot.wave_scope")
                    dag_item = self._evidence_item(state.phase(2).evidence, "dependency_dag")
                    try:
                        dag = json.loads(dag_item.split(": ", 1)[1])
                        expected_dependencies = {
                            (f"issue-{first}", f"issue-{second}") for first, second in dag["edges"]
                        }
                        entries = wave.get("entries") if wave else None
                        if not isinstance(entries, list):
                            raise ValueError("native wave entries unavailable")
                        actual_dependencies = {
                            (original(dependency), original(entry["delegation_id"]))
                            for entry in entries
                            for dependency in entry["depends_on"]
                        }
                        if actual_dependencies != expected_dependencies:
                            failures.append("autopilot.wave_dependencies")
                    except AttributeError, IndexError, KeyError, TypeError, ValueError:
                        failures.append("autopilot.wave_dependencies")
            except ValueError, KeyError:
                failures.append("native_wave_receipt")
        if state.skill == "evaluate-harness":
            failures.extend(self._evaluate_harness_semantic_failures(state, phase, evidence, store))
        if state.skill == "review-code" and phase.name == "execute":
            if status == "skipped":
                failures.append("review_code.skip_forbidden")
            elif status == "completed":
                failures.extend(self._review_code_semantic_failures(evidence, store))
        return failures

    def _adaptive_control_transition_failures(
        self,
        state: PhaseRunState,
        phase: PhaseContract,
        store: PhaseRunStore,
    ) -> list[str]:
        """Every nonterminal transition을 current intent, authority, decision에 결속합니다."""
        try:
            readback = store.read_adaptive_control_transition()
        except AdaptiveControlAuthorityError, AdaptiveControlStoreError:
            return ["adaptive_control_transition.readback"]
        failures: list[str] = []
        if (
            not readback.receipt.ambiguity.ready
            or readback.receipt.ambiguity.action is not ControlAction.CONTINUE
        ):
            failures.append("adaptive_control_transition.ambiguity")
        if (
            readback.authority.workflow_id != readback.receipt.workflow_id
            or readback.authority.workflow_revision != readback.receipt.workflow_revision
            or readback.authority.goal_fingerprint != readback.receipt.goal_fingerprint
        ):
            failures.append("adaptive_control_transition.identity")
        action = readback.receipt.decision.action
        final_phase = phase.id == state.phases[-1].id
        if final_phase:
            if action is not ControlAction.COMPLETE:
                failures.append("adaptive_control_transition.decision")
            if not readback.authority.complete:
                failures.append("adaptive_control_transition.authority")
            return failures
        if action in {ControlAction.CONTINUE, ControlAction.COMPLETE}:
            if not readback.authority.complete:
                failures.append("adaptive_control_transition.authority")
            return failures
        if action is ControlAction.AWAIT_USER:
            failures.extend(self._adaptive_await_user_transition_failures(readback))
            return failures
        failures.append("adaptive_control_transition.decision")
        return failures

    def _adaptive_terminal_transition_failures(
        self,
        status: str,
        store: PhaseRunStore,
    ) -> list[str]:
        """Adaptive terminal을 current external blocker 또는 typed failure에만 결속합니다."""
        try:
            readback = store.read_adaptive_control_transition()
        except AdaptiveControlAuthorityError, AdaptiveControlStoreError:
            return ["adaptive_control_terminal.readback"]
        receipt = readback.receipt
        failures: list[str] = []
        if status == "blocked":
            if (
                receipt.decision.action is not ControlAction.BLOCKED
                or receipt.ambiguity.action is not ControlAction.BLOCKED
            ):
                failures.append("adaptive_control_terminal.decision")
            selected_gap_id = receipt.ambiguity.selected_gap_id
            if selected_gap_id is None or selected_gap_id not in readback.blocker_gap_ids:
                failures.append("adaptive_control_terminal.blocker")
        elif status == "failed" and readback.execution_status is not ExecutionStatus.FAILED:
            failures.append("adaptive_control_terminal.failure")
        if (
            readback.authority.workflow_id != receipt.workflow_id
            or readback.authority.workflow_revision != receipt.workflow_revision
            or readback.authority.goal_fingerprint != receipt.goal_fingerprint
        ):
            failures.append("adaptive_control_terminal.identity")
        if not readback.authority.complete:
            failures.append("adaptive_control_terminal.authority")
        return failures

    def _adaptive_await_user_transition_failures(
        self,
        readback: AdaptiveControlTransitionReadback,
    ) -> list[str]:
        """AWAIT_USER를 exact pending USER_ACCEPTANCE scope에만 허용합니다."""
        attainment = readback.receipt.attainment
        criterion_ids = frozenset(criterion.criterion_id for criterion in readback.criteria)
        pending = frozenset(attainment.pending)
        pending_criteria = pending & criterion_ids
        pending_user_criteria = frozenset(
            criterion.criterion_id
            for criterion in readback.criteria
            if criterion.criterion_id in pending_criteria
            and EvidenceKind.USER_ACCEPTANCE in criterion.required_evidence
        )
        allowed_attainment = pending_user_criteria | {"goal-coverage", "execution"}
        allowed_authority = frozenset(
            f"criterion:{criterion_id}" for criterion_id in pending_user_criteria
        ) | {"goal-coverage"}
        failures: list[str] = []
        if (
            not readback.receipt.ambiguity.ready
            or readback.receipt.ambiguity.action is not ControlAction.CONTINUE
            or not pending_user_criteria
            or pending_criteria != pending_user_criteria
            or not pending.issubset(allowed_attainment)
            or attainment.failed
            or attainment.stale
            or not set(readback.authority.pending_claims).issubset(allowed_authority)
        ):
            failures.append("adaptive_control_transition.await_user")
        return failures

    def required_evidence(
        self,
        state: PhaseRunState,
        phase: PhaseContract,
        status: str,
    ) -> tuple[str, ...]:
        """Adaptive policy를 skill별 분기 없이 first/final phase에 합성합니다."""
        if status in TERMINAL_PHASE_STATUSES:
            return ()
        if (
            state.skill == "finish-session"
            and status == "skipped"
            and phase.name in {"stage_scope", "commit"}
        ):
            return ("clean_tree",)
        required = list(phase.required_evidence)
        if not state.adaptive_control_required:
            return tuple(required)
        first_phase_id = state.phases[0].id
        final_phase_id = state.phases[-1].id
        if phase.id == final_phase_id:
            if "adaptive_control_receipt" not in required:
                required.append("adaptive_control_receipt")
        elif phase.id == first_phase_id and "adaptive_control_initialized" not in required:
            required.append("adaptive_control_initialized")
        return tuple(required)

    def _adaptive_control_initialized_failures(
        self,
        state: PhaseRunState,
        evidence: tuple[str, ...],
        store: PhaseRunStore,
    ) -> list[str]:
        """Initial adaptive state가 구현을 시작할 수 있는 current snapshot인지 확인합니다.

        ASK_USER는 Stop hook의 awaiting-input terminal flow로 사용자에게 질문을
        전달해야 하며, RESEARCH/BLOCKED도 각 source authority에서 먼저 해소해야
        합니다. 반면 ambiguity가 ready인 AWAIT_USER는 intent gap이 아닌 별도의
        goal-acceptance 상태이므로 initialization read-back을 막지 않습니다.
        """
        readback = self._adaptive_control_readback(
            "adaptive_control_initialized",
            evidence,
            store,
            state.north_star,
        )
        if isinstance(readback, list):
            return readback
        receipt = readback.receipt
        authority = readback.authority
        failures: list[str] = []
        if not receipt.ambiguity.ready or receipt.ambiguity.action is not ControlAction.CONTINUE:
            failures.append("adaptive_control_initialized.ambiguity")
        if (
            authority.workflow_id != receipt.workflow_id
            or authority.workflow_revision != receipt.workflow_revision
            or authority.goal_fingerprint != receipt.goal_fingerprint
        ):
            failures.append("adaptive_control_initialized.identity")
        return failures

    def _adaptive_control_receipt_failures(
        self,
        evidence: tuple[str, ...],
        store: PhaseRunStore,
    ) -> list[str]:
        """문자열 label이 아니라 exact current receipt와 external authority를 검증합니다."""
        readback = self._adaptive_control_readback(
            "adaptive_control_receipt",
            evidence,
            store,
            None,
        )
        if isinstance(readback, list):
            return readback
        receipt = readback.receipt
        authority = readback.authority
        failures: list[str] = []
        if receipt.decision.action is not ControlAction.COMPLETE:
            failures.append("adaptive_control_receipt.action")
        if not (
            receipt.ambiguity.ready and receipt.attainment.achieved and receipt.decision.achieved
        ):
            failures.append("adaptive_control_receipt.attainment")
        if not authority.complete:
            failures.append("adaptive_control_receipt.authority")
        if (
            authority.workflow_id != receipt.workflow_id
            or authority.workflow_revision != receipt.workflow_revision
            or authority.goal_fingerprint != receipt.goal_fingerprint
        ):
            failures.append("adaptive_control_receipt.identity")
        return failures

    def _adaptive_control_readback(
        self,
        evidence_key: str,
        evidence: tuple[str, ...],
        store: PhaseRunStore,
        north_star: str | None,
    ) -> AdaptiveControlPhaseReadback | list[str]:
        items = [item for item in evidence if item.partition(":")[0].strip() == evidence_key]
        if len(items) != 1:
            return [f"{evidence_key}.label"]
        try:
            candidate = self._strict_json_object(items[0].partition(":")[2].strip())
            readback = store.verify_adaptive_control_evidence(candidate)
            if north_star is not None and readback.contract_goal.strip() != north_star.strip():
                return [f"{evidence_key}.goal"]
            return readback
        except (
            AdaptiveControlAuthorityError,
            AdaptiveControlStoreError,
            TypeError,
            ValueError,
        ):
            return [f"{evidence_key}.readback"]

    def _strict_json_object(self, raw_value: str) -> dict[str, object]:
        """Duplicate key와 non-object JSON을 거부하는 phase evidence decoder입니다."""

        def object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
            """JSON key-value pair를 중복 없는 object로 변환합니다.

            Args:
                pairs: Decoder가 source 순서로 전달한 JSON object pair입니다.

            Returns:
                중복 key가 없는 string-keyed object입니다.

            Raises:
                ValueError: 같은 key가 두 번 나타나면 발생합니다.
            """
            decoded: dict[str, object] = {}
            for key, value in pairs:
                if key in decoded:
                    raise ValueError(f"duplicate JSON key: {key}")
                decoded[key] = value
            return decoded

        decoded = json.loads(raw_value, object_pairs_hook=object_pairs)
        if not isinstance(decoded, dict) or any(not isinstance(key, str) for key in decoded):
            raise ValueError("adaptive control receipt must be a JSON object")
        return {str(key): value for key, value in decoded.items()}

    def _review_code_semantic_failures(
        self,
        evidence: tuple[str, ...],
        store: PhaseRunStore,
    ) -> list[str]:
        """Review receipt를 shared consumed delegation evidence와 exact하게 대조합니다."""
        failures: list[str] = []
        items: dict[str, str] = {}
        for key in (
            "subagent_dispatch",
            "diff_marker",
            "persona_readback",
            "review_categories",
            "delegate_transition_receipt",
            "review_report_readback",
        ):
            matches = [item for item in evidence if item.partition(":")[0].strip() == key]
            if len(matches) != 1:
                failures.append(f"{key}.label")
                items[key] = ""
            else:
                items[key] = matches[0]

        dispatch = items["subagent_dispatch"]
        diff_marker = items["diff_marker"]
        persona = items["persona_readback"]
        categories = items["review_categories"]
        transition = items["delegate_transition_receipt"]
        readback = items["review_report_readback"]
        head_sha = self._evidence_value(diff_marker, "head_sha")
        failures.extend(self._exact_head_failures("diff_marker", head_sha))
        if (
            self._evidence_value(persona, "policy_id") != POLICY_ID
            or self._evidence_value(persona, "categories") != REVIEW_CODE_ROW_COUNT_TEXT
        ):
            failures.append("persona_readback.policy")
        if self._evidence_value(categories, "verified") != REVIEW_CODE_ROW_COUNT_TEXT:
            failures.append("review_categories.verified")

        selected_delegation_id = self._evidence_value(transition, "delegation_id")
        if not selected_delegation_id:
            failures.append("delegate_transition_receipt.identity")
            return failures
        try:
            snapshot, verification = store.read_review_evidence(
                "review-code", head_sha, delegation_id=selected_delegation_id
            )
        except DelegationEvidenceError:
            failures.append("delegation_evidence.readback")
            return failures

        delegation_id = str(snapshot.delegation_id)
        agent_id = str(snapshot.target_actor_id)
        outcome_ref = snapshot.outcome_ref
        if (
            self._evidence_value(dispatch, "delegation_id") != delegation_id
            or self._evidence_value(dispatch, "agent_id") != agent_id
            or self._evidence_value(dispatch, "outcome") != "result-applied"
            or snapshot.kind != "review-code"
            or snapshot.reviewed_head_sha != head_sha
        ):
            failures.append("delegation_evidence.identity")
        if (
            self._evidence_value(transition, "delegation_id") != delegation_id
            or self._evidence_value(transition, "target_agent_id") != agent_id
            or self._evidence_value(transition, "outcome_ref") != outcome_ref
        ):
            failures.append("delegate_transition_receipt.identity")

        report = snapshot.report_payload()
        review_notes = report.get("review_notes")
        failures.extend(self._review_note_failures(review_notes, set(verification.verified_rows)))
        note_count = len(review_notes) if isinstance(review_notes, list) else -1
        try:
            readback_notes = int(self._evidence_value(readback, "note_count"))
            readback_blockers = int(self._evidence_value(readback, "blocker_count"))
        except ValueError:
            readback_notes = readback_blockers = -1
        if (
            self._evidence_value(readback, "outcome_ref") != outcome_ref
            or readback_notes != note_count
            or readback_blockers != verification.blocking_finding_count
            or self._evidence_value(readback, "verdict") != verification.verdict
        ):
            failures.append("review_report_readback.content")
        return failures

    def _review_note_failures(self, value: object, row_ids: set[str]) -> list[str]:
        """Nonblocking review note가 처리 경로와 검증 본문을 보존하는지 검사합니다."""
        if not isinstance(value, list):
            return ["review_notes.collection"]
        required_fields = {
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
        }
        failures: list[str] = []
        stable_keys: list[str] = []
        root_keys: list[str] = []
        for index, raw in enumerate(value):
            if not isinstance(raw, dict) or set(raw) != required_fields:
                failures.append(f"review_notes.{index}.fields")
                continue
            if any(
                not isinstance(raw[field], str) or not raw[field].strip() or "\n" in raw[field]
                for field in required_fields
            ):
                failures.append(f"review_notes.{index}.evidence")
                continue
            stable_key = raw["stable_key"]
            root_key = raw["root_cause_key"]
            stable_keys.append(stable_key)
            root_keys.append(root_key)
            if (
                re.fullmatch(r"[A-Z0-9][A-Z0-9._-]{2,127}", stable_key) is None
                or re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,127}", root_key) is None
                or raw["row_id"] not in row_ids
            ):
                failures.append(f"review_notes.{index}.identity")
            if raw["severity"] == "warning":
                if raw["disposition"] != "gap-triage" or raw["expected"] == raw["actual"]:
                    failures.append(f"review_notes.{index}.warning_disposition")
            elif raw["severity"] == "resolved":
                if (
                    raw["disposition"] not in {"rebutted", "fixed"}
                    or raw["expected"] != raw["actual"]
                ):
                    failures.append(f"review_notes.{index}.resolved_evidence")
            else:
                failures.append(f"review_notes.{index}.severity")
        if len(stable_keys) != len(set(stable_keys)):
            failures.append("review_notes.stable_key_deduplication")
        if len(root_keys) != len(set(root_keys)):
            failures.append("review_notes.root_cause_deduplication")
        return failures

    def _publication_semantic_failures(self, evidence: tuple[str, ...]) -> list[str]:
        """Final local review, commit, push evidence가 같은 exact head인지 검증합니다."""
        local_review = self._evidence_item(evidence, "local_review_head_sha")
        matrix_receipt = self._evidence_item(evidence, "local_review_matrix_receipt")
        commit = self._evidence_item(evidence, "commit_sha")
        pushed = self._evidence_item(evidence, "push_head_match")
        local_head = self._head_evidence_value(local_review)
        commit_head = self._head_evidence_value(commit)
        pushed_head = self._head_evidence_value(pushed)
        failures: list[str] = []
        if (
            "kind=final-local-review" not in local_review
            or "outcome=result-applied" not in local_review
            or re.fullmatch(r"[0-9a-f]{40}", local_head) is None
        ):
            failures.append("local_review_head_sha.receipt")
        if commit_head != local_head:
            failures.append("commit_sha.local_review_mismatch")
        if pushed_head != local_head:
            failures.append("push_head_match.local_review_mismatch")
        failures.extend(self._exact_head_failures("commit_sha", commit_head))
        failures.extend(self._push_head_match_semantic_failures(evidence))
        failures.extend(self._local_review_matrix_receipt_failures(matrix_receipt, local_head))
        return failures

    def _push_head_match_semantic_failures(self, evidence: tuple[str, ...]) -> list[str]:
        """Structured push evidence를 current local과 live remote exact head에 결속합니다."""
        pushed = self._evidence_item(evidence, "push_head_match")
        pushed_head = self._head_evidence_value(pushed)
        pushed_local = self._evidence_value(pushed, "local_sha")
        pushed_remote = self._evidence_value(pushed, "remote_sha")
        failures: list[str] = []
        if pushed_local != pushed_head:
            failures.append("push_head_match.local_sha_mismatch")
        if pushed_remote != pushed_head or not self._evidence_flag(pushed, "match"):
            failures.append("push_head_match.remote_sha_mismatch")
        failures.extend(self._exact_head_failures("push_head_match", pushed_head))
        failures.extend(self._push_upstream_failures(pushed_remote))
        return failures

    def _push_upstream_failures(self, pushed_head: str) -> list[str]:
        """Push evidence를 실제 upstream ref read-back에 결속합니다."""
        if not self._repository.head():
            return []
        upstream_head = self._repository.upstream_head()
        if not upstream_head:
            return ["push_head_match.upstream_readback"]
        if pushed_head != upstream_head:
            return ["push_head_match.upstream_mismatch"]
        return []

    def _local_review_matrix_receipt_failures(
        self,
        receipt: str,
        expected_head: str,
    ) -> list[str]:
        """Final local review의 frozen 14-row pass receipt를 exact head에 결속합니다."""
        if not receipt:
            return ["local_review_matrix_receipt.missing"]
        failures: list[str] = []
        matrix_id = self._evidence_value(receipt, "matrix_id")
        head_sha = self._evidence_value(receipt, "head_sha")
        expected_tokens = {
            "frozen": "true",
            "row_count": REVIEW_CODE_ROW_COUNT_TEXT,
            "verified_rows": REVIEW_CODE_ROW_COUNT_TEXT,
            "blocking_findings": "0",
            "verdict": "pass",
            "harness_audit": "true",
            "audit_evidence": "3",
            "kind": "final-local-review",
            "outcome": "result-applied",
        }
        if re.fullmatch(r"[0-9a-f]{64}", matrix_id) is None:
            failures.append("local_review_matrix_receipt.matrix_id")
        if head_sha != expected_head or re.fullmatch(r"[0-9a-f]{40}", head_sha) is None:
            failures.append("local_review_matrix_receipt.head_sha")
        for key, expected in expected_tokens.items():
            if self._evidence_value(receipt, key) != expected:
                failures.append(f"local_review_matrix_receipt.{key}")
        return failures

    def _evaluate_harness_semantic_failures(
        self,
        state: PhaseRunState,
        phase: PhaseContract,
        evidence: tuple[str, ...],
        store: PhaseRunStore,
    ) -> list[str]:
        """Evaluate-harness evidence를 frozen matrix identity와 exact head에 결속합니다.

        Args:
            state: 이전 phase evidence를 포함한 current run state입니다.
            phase: 현재 evaluate-harness phase 계약입니다.
            evidence: 현재 phase가 제출한 evidence 항목입니다.

        Returns:
            구조 또는 cross-phase identity가 불완전한 field 이름입니다.
        """
        structured_keys = {
            "acceptance_matrix",
            "finding_reproduction",
            "fixed_matrix_verification_result",
            "harness_evolution_result",
        }
        if structured_keys.isdisjoint(phase.required_evidence):
            return []
        if "acceptance_matrix" in phase.required_evidence:
            inventory_failures = self._source_capability_inventory_failures(
                self._evidence_item(evidence, "source_capability_inventory")
            )
            if inventory_failures:
                return inventory_failures
            return self._acceptance_matrix_failures(
                self._evidence_item(evidence, "acceptance_matrix")
            )
        matrix = self._previous_evidence_item(state, "acceptance_matrix")
        matrix_failures = self._acceptance_matrix_failures(
            matrix,
            require_current_worktree=(
                "fixed_matrix_verification_result" not in phase.required_evidence
            ),
        )
        if matrix_failures:
            return [f"previous_{failure}" for failure in matrix_failures]
        if "finding_reproduction" in phase.required_evidence:
            return self._independent_evaluation_evidence_failures(matrix, evidence, store)
        if "fixed_matrix_verification_result" in phase.required_evidence:
            return self._fixed_matrix_verification_failures(state, matrix, evidence)
        return []

    def _source_capability_inventory_failures(self, inventory: str) -> list[str]:
        """조사 기록의 일관성과 실제 source manifest를 검증합니다.

        Pass counts는 조사자가 남긴 기록이며 의미적 포화를 증명하지 않습니다.
        Machine authority는 exact source bytes, 파일 목록과 실제 참조에 한정합니다.
        """
        failures: list[str] = []
        source_sha = self._evidence_value(inventory, "source_sha")
        if re.fullmatch(r"[0-9a-f]{40}", source_sha) is None:
            failures.append("source_capability_inventory.source_sha")

        try:
            pass_count = int(self._evidence_value(inventory, "pass_count"))
        except ValueError:
            pass_count = -1
        if pass_count < 2:
            failures.append("source_capability_inventory.pass_count")

        raw_counts = self._pipe_values(self._evidence_value(inventory, "new_capability_counts"))
        counts: list[int] = []
        try:
            counts = [int(value) for value in raw_counts]
        except ValueError:
            failures.append("source_capability_inventory.new_capability_counts")
        if len(counts) != pass_count or any(value < 0 for value in counts):
            failures.append("source_capability_inventory.new_capability_counts")
        elif counts[0] < 1 or counts[-1] != 0 or any(value < 1 for value in counts[:-1]):
            failures.append("source_capability_inventory.saturation")

        capability_ids = self._pipe_values(self._evidence_value(inventory, "capability_ids"))
        if (
            not capability_ids
            or len(capability_ids) != len(set(capability_ids))
            or any(
                re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", value) is None for value in capability_ids
            )
        ):
            failures.append("source_capability_inventory.capability_ids")
        try:
            capability_count = int(self._evidence_value(inventory, "capability_count"))
        except ValueError:
            capability_count = -1
        if capability_count != len(capability_ids) or (counts and capability_count != sum(counts)):
            failures.append("source_capability_inventory.capability_count")
        try:
            source_files = int(self._evidence_value(inventory, "source_files"))
        except ValueError:
            source_files = 0
        if source_files < 1:
            failures.append("source_capability_inventory.source_files")
        if not self._evidence_flag(inventory, "complete"):
            failures.append("source_capability_inventory.complete")
        if not self._evidence_flag(inventory, "saturated"):
            failures.append("source_capability_inventory.saturated")
        if not HarnessSourceInventory(self._root).verify(
            reference=self._evidence_value(inventory, "manifest"),
            digest=self._evidence_value(inventory, "manifest_sha"),
            source_sha=source_sha,
            capability_ids=capability_ids,
            source_files=source_files,
            regression_node_exists=self._repository.valid_regression_node,
        ):
            failures.append("source_capability_inventory.manifest")
        return list(dict.fromkeys(failures))

    def _acceptance_matrix_failures(
        self,
        matrix: str,
        *,
        require_current_worktree: bool = True,
    ) -> list[str]:
        """Frozen matrix의 row/decision digest와 exact worktree bytes를 검증합니다."""
        matrix_id = self._evidence_value(matrix, "matrix_id")
        head_sha = self._evidence_value(matrix, "head_sha")
        worktree_sha = self._evidence_value(matrix, "worktree_sha")
        rows_text = self._evidence_value(matrix, "rows")
        row_specs_text = self._evidence_value(matrix, "row_specs")
        decisions_text = self._evidence_value(matrix, "decisions")
        row_nodes_text = self._evidence_value(matrix, "row_nodes")
        row_nodes = self._row_node_map(row_nodes_text)
        rows = self._pipe_values(rows_text)
        row_specs = self._row_spec_map(row_specs_text)
        decisions = self._decision_map(decisions_text)
        failures: list[str] = []
        if not self._evidence_flag(matrix, "frozen"):
            failures.append("acceptance_matrix.frozen")
        failures.extend(self._exact_head_failures("acceptance_matrix", head_sha))
        if re.fullmatch(r"[0-9a-f]{64}", worktree_sha) is None:
            failures.append("acceptance_matrix.worktree_sha")
        elif require_current_worktree and worktree_sha != self._repository.worktree_sha():
            failures.append("acceptance_matrix.current_worktree")
        if len(rows) < 2 or len(rows) != len(set(rows)):
            failures.append("acceptance_matrix.rows")
        try:
            row_count = int(self._evidence_value(matrix, "row_count"))
        except ValueError:
            row_count = -1
        if row_count != len(rows):
            failures.append("acceptance_matrix.row_count")
        if set(row_specs) != set(rows):
            failures.append("acceptance_matrix.row_specs")
        if (
            set(row_nodes) != set(rows)
            or len(set(row_nodes.values())) != len(row_nodes)
            or any(not self._repository.valid_regression_node(node) for node in row_nodes.values())
        ):
            failures.append("acceptance_matrix.row_nodes")
        allowed_decisions = {
            "allow",
            "deny",
            "defer",
            "fail_closed",
            "preserve",
            "refreeze_and_verify",
            "terminate_then_allow",
        }
        if set(decisions) != set(rows) or any(
            decision not in allowed_decisions for decision in decisions.values()
        ):
            failures.append("acceptance_matrix.decisions")
        expected_id = hashlib.sha256(
            (
                f"{head_sha}|{worktree_sha}|{rows_text}|{row_specs_text}|{decisions_text}|{row_nodes_text}"
            ).encode()
        ).hexdigest()
        if matrix_id != expected_id:
            failures.append("acceptance_matrix.matrix_id")
        return failures

    def _independent_evaluation_evidence_failures(
        self,
        matrix: str,
        evidence: tuple[str, ...],
        store: PhaseRunStore,
    ) -> list[str]:
        """Finding reproduction, evaluator report, dedup, row classification을 교차 검증합니다."""
        matrix_id = self._evidence_value(matrix, "matrix_id")
        head_sha = self._evidence_value(matrix, "head_sha")
        worktree_sha = self._evidence_value(matrix, "worktree_sha")
        matrix_rows = set(self._pipe_values(self._evidence_value(matrix, "rows")))
        matrix_decisions = self._decision_map(self._evidence_value(matrix, "decisions"))
        mapping = self._evidence_item(evidence, "project_mapping")
        report = self._evidence_item(evidence, "independent_evaluator_report")
        reproduction = self._evidence_item(evidence, "finding_reproduction")
        deduplication = self._evidence_item(evidence, "root_cause_deduplication")
        classification = self._evidence_item(evidence, "enforcement_classification")
        failures: list[str] = []

        if (
            self._evidence_value(mapping, "matrix_id") != matrix_id
            or set(self._pipe_values(self._evidence_value(mapping, "mapped_rows"))) != matrix_rows
        ):
            failures.append("project_mapping.matrix_rows")
        delegation_id = self._evidence_value(report, "delegation_id")
        outcome_ref = self._evidence_value(report, "outcome_ref")
        if not delegation_id or not outcome_ref:
            failures.append("independent_evaluator_report.delegation_pointer")
        if (
            self._evidence_value(report, "head_sha") != head_sha
            or self._evidence_value(report, "worktree_sha") != worktree_sha
        ):
            failures.append("independent_evaluator_report.source_identity")
        try:
            blocking_findings = int(self._evidence_value(report, "blocking_findings"))
        except ValueError:
            blocking_findings = -1
        if blocking_findings < 0:
            failures.append("independent_evaluator_report.blocking_findings")
        artifact_blocker_ids: set[str] | None = None
        try:
            readback = store.read_consumed_delegation_evidence(
                "evaluate-harness-independent-evaluator",
                head_sha,
            )
        except DelegationEvidenceError:
            failures.append("independent_evaluator_report.delegation_readback")
        else:
            artifact_report = readback.report_payload()
            artifact_blockers = artifact_report.get("blocking_findings")
            if (
                delegation_id != str(readback.delegation_id)
                or outcome_ref != readback.outcome_ref
                or artifact_report.get("matrix_id") != matrix_id
                or artifact_report.get("head_sha") != head_sha
                or artifact_report.get("worktree_sha") != worktree_sha
                or not isinstance(artifact_blockers, list)
                or any(not isinstance(item, str) for item in artifact_blockers)
                or len(artifact_blockers) != blocking_findings
                or len(set(artifact_blockers)) != len(artifact_blockers)
            ):
                failures.append("independent_evaluator_report.delegation_readback")
            else:
                artifact_blocker_ids = set(artifact_blockers)

        finding_ids = self._pipe_values(self._evidence_value(reproduction, "finding_ids"))
        reproduction_specs = self._reproduction_spec_map(
            self._evidence_value(reproduction, "reproduction_specs")
        )
        reproduction_nodes = self._row_node_map(
            self._evidence_value(reproduction, "reproduction_nodes")
        )
        if (
            self._evidence_value(reproduction, "matrix_id") != matrix_id
            or self._evidence_value(reproduction, "head_sha") != head_sha
            or self._evidence_value(reproduction, "worktree_sha") != worktree_sha
            or not self._evidence_flag(reproduction, "reproduced")
            or len(finding_ids) != len(set(finding_ids))
            or set(reproduction_specs) != set(finding_ids)
            or any(
                row not in matrix_rows or expected != matrix_decisions.get(row)
                for row, expected, _actual, _command_hash in reproduction_specs.values()
            )
        ):
            failures.append("finding_reproduction.identity")
        if not finding_ids and any(
            self._evidence_value(reproduction, key) != "none"
            for key in ("finding_ids", "reproduction_specs", "reproduction_nodes")
        ):
            failures.append("finding_reproduction.identity")
        invalid_nodes = set(reproduction_nodes) != set(finding_ids) or any(
            not self._repository.valid_regression_node(node) for node in reproduction_nodes.values()
        )
        if invalid_nodes:
            failures.append("finding_reproduction.reproduction_nodes")
        frozen_nodes = self._row_node_map(self._evidence_value(matrix, "row_nodes"))
        if any(
            reproduction_nodes.get(finding_id) != frozen_nodes.get(spec[0])
            for finding_id, spec in reproduction_specs.items()
        ):
            failures.append("finding_reproduction.row_node_identity")
        try:
            commands = int(self._evidence_value(reproduction, "commands"))
            expected_actual_pairs = int(self._evidence_value(reproduction, "expected_actual_pairs"))
        except ValueError:
            commands = expected_actual_pairs = -1
        if commands != len(finding_ids) or expected_actual_pairs != len(finding_ids):
            failures.append("finding_reproduction.receipts")
        reproduced_blockers = sum(
            expected != actual
            for _row, expected, actual, _command_hash in reproduction_specs.values()
        )
        if blocking_findings != reproduced_blockers:
            failures.append("independent_evaluator_report.reproduced_blockers")
        mismatch_ids = {
            finding_id
            for finding_id, (_row, expected, actual, _command_hash) in reproduction_specs.items()
            if expected != actual
        }
        if artifact_blocker_ids is not None and artifact_blocker_ids != mismatch_ids:
            failures.append("independent_evaluator_report.finding_ids")
        if not failures and not invalid_nodes:
            for finding_id in sorted(finding_ids):
                _row, expected, actual, _command_hash = reproduction_specs[finding_id]
                exit_code = self._repository.run_regression_node(reproduction_nodes[finding_id])
                if exit_code != (0 if expected == actual else 1):
                    failures.append("finding_reproduction.execution")
            if self._repository.worktree_sha() != worktree_sha:
                failures.append("finding_reproduction.current_worktree")

        dedup_findings = self._pipe_values(self._evidence_value(deduplication, "finding_ids"))
        stable_rules = self._pipe_values(self._evidence_value(deduplication, "stable_rule_ids"))
        dedup_specs = self._dedup_spec_map(self._evidence_value(deduplication, "dedup_specs"))
        if (
            self._evidence_value(deduplication, "matrix_id") != matrix_id
            or set(dedup_findings) != set(finding_ids)
            or (bool(finding_ids) != bool(stable_rules))
            or len(stable_rules) != len(set(stable_rules))
            or set(dedup_specs) != set(finding_ids)
            or set(dedup_specs.values()) != set(stable_rules)
            or not self._evidence_flag(deduplication, "mapped")
        ):
            failures.append("root_cause_deduplication.mapping")
        if not finding_ids and any(
            self._evidence_value(deduplication, key) != "none"
            for key in ("finding_ids", "stable_rule_ids", "dedup_specs")
        ):
            failures.append("root_cause_deduplication.mapping")

        classified_rows = set(
            self._pipe_values(self._evidence_value(classification, "classified_rows"))
        )
        classified_sets = [
            set(self._pipe_values(self._evidence_value(classification, key)))
            for key in ("strong_rows", "weak_rows", "failed_rows")
        ]
        classified_union = set().union(*classified_sets)
        overlap = sum(len(values) for values in classified_sets) != len(classified_union)
        if (
            self._evidence_value(classification, "matrix_id") != matrix_id
            or classified_rows != matrix_rows
            or classified_union != matrix_rows
            or overlap
        ):
            failures.append("enforcement_classification.rows")
        return failures

    def _fixed_matrix_verification_failures(
        self,
        state: PhaseRunState,
        matrix: str,
        evidence: tuple[str, ...],
    ) -> list[str]:
        """Current worktree에서 frozen row node를 실행해 agent receipt와 대조합니다."""
        matrix_id = self._evidence_value(matrix, "matrix_id")
        head_sha = self._evidence_value(matrix, "head_sha")
        matrix_rows = set(self._pipe_values(self._evidence_value(matrix, "rows")))
        verification = self._evidence_item(evidence, "verification_result")
        fixed = self._evidence_item(evidence, "fixed_matrix_verification_result")
        evolution = self._evidence_item(evidence, "harness_evolution_result")
        worktree_sha = self._repository.worktree_sha()
        fixed_worktree_sha = self._evidence_value(fixed, "worktree_sha")
        result = self._evidence_value(fixed, "result").casefold()
        action = self._evidence_value(evolution, "action").casefold()
        failures: list[str] = []
        try:
            row_count = int(self._evidence_value(fixed, "row_count"))
        except ValueError:
            row_count = -1
        fixed_rows = set(self._pipe_values(self._evidence_value(fixed, "rows")))
        if (
            self._evidence_value(fixed, "matrix_id") != matrix_id
            or self._evidence_value(fixed, "head_sha") != head_sha
            or re.fullmatch(r"[0-9a-f]{64}", fixed_worktree_sha) is None
            or fixed_worktree_sha != worktree_sha
            or fixed_rows != matrix_rows
            or row_count != len(matrix_rows)
        ):
            failures.append("fixed_matrix_verification_result.matrix")
        row_nodes = self._row_node_map(self._evidence_value(fixed, "row_nodes"))
        invalid_nodes = (
            set(row_nodes) != matrix_rows
            or len(set(row_nodes.values())) != len(row_nodes)
            or any(not self._repository.valid_regression_node(node) for node in row_nodes.values())
        )
        if row_nodes != self._row_node_map(self._evidence_value(matrix, "row_nodes")):
            failures.append("fixed_matrix_verification_result.row_node_identity")
            invalid_nodes = True
        if invalid_nodes:
            failures.append("fixed_matrix_verification_result.row_nodes")
            actual_blockers = -1
        else:
            outcomes = tuple(
                self._repository.run_regression_node(row_nodes[row]) for row in sorted(matrix_rows)
            )
            actual_blockers = (
                -1
                if RegressionNodeOutcome.ERROR in outcomes
                else sum(outcome is RegressionNodeOutcome.FAILURE for outcome in outcomes)
            )
        try:
            declared_blockers = int(self._evidence_value(fixed, "blocking_findings"))
        except ValueError:
            declared_blockers = -1
        expected_result = (
            "approach_change_required" if action == "approach_change_required" else "pass"
        )
        if (
            result != expected_result
            or declared_blockers != actual_blockers
            or (result == "pass" and actual_blockers != 0)
            or (result == "approach_change_required" and actual_blockers <= 0)
        ):
            failures.append("fixed_matrix_verification_result.execution")
        verification_expected = {
            "matrix_id": matrix_id,
            "head_sha": head_sha,
            "worktree_sha": worktree_sha,
            "result": result,
            "row_count": str(len(matrix_rows)),
            "blocking_findings": str(actual_blockers),
        }
        if any(
            self._evidence_value(verification, key) != expected
            for key, expected in verification_expected.items()
        ):
            failures.append("verification_result.mechanical_readback")
        failures.extend(
            self._exact_head_failures(
                "fixed_matrix_verification_result",
                self._evidence_value(fixed, "head_sha"),
            )
        )
        failures.extend(self._harness_evolution_failures(state, matrix, evidence))
        return failures

    def _harness_evolution_failures(
        self,
        state: PhaseRunState,
        matrix: str,
        evidence: tuple[str, ...],
    ) -> list[str]:
        """Accepted evaluation feedback가 durable gate와 regression으로 승격됐는지 검증합니다."""
        evolution = self._evidence_item(evidence, "harness_evolution_result")
        reproduction = self._previous_evidence_item(state, "finding_reproduction")
        matrix_id = self._evidence_value(matrix, "matrix_id")
        head_sha = self._evidence_value(matrix, "head_sha")
        current_worktree_sha = self._repository.worktree_sha()
        finding_ids = set(self._pipe_values(self._evidence_value(reproduction, "finding_ids")))
        evolution_findings = set(self._pipe_values(self._evidence_value(evolution, "finding_ids")))
        action = self._evidence_value(evolution, "action").casefold()
        harness_paths = self._pipe_values(self._evidence_value(evolution, "harness_paths"))
        regression_nodes = self._pipe_values(self._evidence_value(evolution, "regression_nodes"))
        failures: list[str] = []
        if (
            self._evidence_value(evolution, "matrix_id") != matrix_id
            or self._evidence_value(evolution, "head_sha") != head_sha
            or self._evidence_value(evolution, "worktree_sha") != current_worktree_sha
            or evolution_findings != finding_ids
            or action not in {"promote", "no_change", "approach_change_required", "defer"}
        ):
            failures.append("harness_evolution_result.identity")

        reproduction_specs = self._reproduction_spec_map(
            self._evidence_value(reproduction, "reproduction_specs")
        )
        reproduction_nodes = self._row_node_map(
            self._evidence_value(reproduction, "reproduction_nodes")
        )
        has_blocker = any(
            expected != actual
            for _row, expected, actual, _command_hash in reproduction_specs.values()
        )
        if has_blocker and action not in {"promote", "approach_change_required"}:
            failures.append("harness_evolution_result.blocking_action")
        if action == "promote":
            if not harness_paths or not regression_nodes:
                failures.append("harness_evolution_result.promotion_artifacts")
            allowed_roots = (
                ".agents/",
                ".claude/",
                ".codex/",
                "scripts/",
            )
            allowed_files = {".pre-commit-config.yaml", "AGENTS.md", "mise.toml"}
            for relative_path in harness_paths:
                candidate = (self._root / relative_path).resolve()
                if (
                    (
                        not relative_path.startswith(allowed_roots)
                        and relative_path not in allowed_files
                    )
                    or not candidate.is_relative_to(self._root)
                    or not candidate.is_file()
                ):
                    failures.append("harness_evolution_result.harness_paths")
                    break
            for node in regression_nodes:
                if not self._repository.valid_regression_node(node):
                    failures.append("harness_evolution_result.regression_nodes")
                    break
            fixed = self._evidence_item(evidence, "fixed_matrix_verification_result")
            fixed_row_nodes = self._row_node_map(self._evidence_value(fixed, "row_nodes"))
            fixed_nodes = set(fixed_row_nodes.values())
            if not set(regression_nodes).issubset(fixed_nodes):
                failures.append("harness_evolution_result.unverified_regression_nodes")
            if set(regression_nodes) != set(reproduction_nodes.values()) or any(
                fixed_row_nodes.get(reproduction_specs[finding_id][0])
                != reproduction_nodes.get(finding_id)
                for finding_id in finding_ids
                if finding_id in reproduction_specs
            ):
                failures.append("harness_evolution_result.finding_regression_linkage")
        elif harness_paths or regression_nodes:
            failures.append("harness_evolution_result.unpromoted_artifacts")
        return failures

    def _row_node_map(self, value: str) -> dict[str, str]:
        """`row@path::test` 목록을 unique row-to-node mapping으로 변환합니다."""
        parsed: dict[str, str] = {}
        for item in self._pipe_values(value):
            row, separator, node = item.partition("@")
            if not separator or not row or not node or row in parsed:
                return {}
            parsed[row] = node
        return parsed

    def _exact_head_failures(self, label: str, head_sha: str) -> list[str]:
        """Evidence head가 Git repository의 exact current commit인지 검증합니다."""
        if re.fullmatch(r"[0-9a-f]{40}", head_sha) is None:
            return [f"{label}.head_sha"]
        current_head = self._repository.head()
        if current_head and head_sha != current_head:
            return [f"{label}.current_head"]
        return []

    def _pipe_values(self, value: str) -> list[str]:
        """`none` 또는 pipe-delimited identity 목록을 정규화합니다."""
        if not value or value.casefold() == "none":
            return []
        return [item for item in value.split("|") if item]

    def _decision_map(self, value: str) -> dict[str, str]:
        """`row:decision` pipe 목록을 중복 없는 mapping으로 변환합니다."""
        decisions: dict[str, str] = {}
        for item in self._pipe_values(value):
            row, separator, decision = item.partition(":")
            if not separator or not row or not decision or row in decisions:
                return {}
            decisions[row] = decision
        return decisions

    def _row_spec_map(self, value: str) -> dict[str, tuple[str, str, str]]:
        """Row를 identity-role/context/capability semantic tuple에 결속합니다."""
        row_specs: dict[str, tuple[str, str, str]] = {}
        token_pattern = re.compile(r"[A-Za-z0-9._-]+")
        for item in self._pipe_values(value):
            parts = item.split(":")
            if len(parts) != 4 or any(token_pattern.fullmatch(part) is None for part in parts):
                return {}
            row, identity_role, execution_context, tool_capability = parts
            if row in row_specs:
                return {}
            row_specs[row] = (identity_role, execution_context, tool_capability)
        return row_specs

    def _reproduction_spec_map(self, value: str) -> dict[str, tuple[str, str, str, str]]:
        """Finding을 matrix row, expected/actual decision, command hash에 결속합니다."""
        specs: dict[str, tuple[str, str, str, str]] = {}
        token_pattern = re.compile(r"[A-Za-z0-9._-]+")
        allowed_decisions = {
            "allow",
            "deny",
            "defer",
            "fail_closed",
            "preserve",
            "refreeze_and_verify",
            "terminate_then_allow",
        }
        for item in self._pipe_values(value):
            parts = item.split(":")
            if len(parts) != 5:
                return {}
            finding_id, row, expected, actual, command_hash = parts
            if (
                finding_id in specs
                or token_pattern.fullmatch(finding_id) is None
                or token_pattern.fullmatch(row) is None
                or expected not in allowed_decisions
                or actual not in allowed_decisions
                or re.fullmatch(r"[0-9a-f]{64}", command_hash) is None
            ):
                return {}
            specs[finding_id] = (row, expected, actual, command_hash)
        return specs

    def _dedup_spec_map(self, value: str) -> dict[str, str]:
        """각 finding을 정확히 하나의 stable rule identity에 매핑합니다."""
        mapping: dict[str, str] = {}
        token_pattern = re.compile(r"[A-Za-z0-9._-]+")
        for item in self._pipe_values(value):
            finding_id, separator, stable_rule_id = item.partition(":")
            if (
                not separator
                or finding_id in mapping
                or token_pattern.fullmatch(finding_id) is None
                or token_pattern.fullmatch(stable_rule_id) is None
            ):
                return {}
            mapping[finding_id] = stable_rule_id
        return mapping

    def _merge_cleanup_semantic_failures(
        self,
        state: PhaseRunState,
        evidence: tuple[str, ...],
    ) -> list[str]:
        approval = self._evidence_item(evidence, "merge_approval")
        agent_session = (
            self._previous_evidence_item(state, "agent_session_context")
            or self._previous_evidence_item(state, "session_workflow_context")
        )
        merge_policy = self._evidence_value(agent_session, "merge_policy")

        failures: list[str] = []
        if not merge_policy:
            failures.append("merge_approval.merge_policy_source")
        if merge_policy == "manual" and not (
            self._evidence_flag(approval, "explicit_user_approval")
            and self._evidence_value(approval, "approved_by") == "user"
        ):
            failures.append("merge_approval.explicit_user_approval")
        if (
            merge_policy == "manual"
            and self._evidence_value(approval, "source") == "github_pr_comment"
        ):
            failures.extend(self._github_pr_comment_approval_failures(evidence, approval))
        if merge_policy == "auto" and not self._evidence_flag(
            approval,
            "auto_merge_invocation",
        ):
            failures.append("merge_approval.auto_merge_invocation")
        failures.extend(self._completed_merge_cleanup_failures(evidence))
        return failures

    def _completed_merge_cleanup_failures(self, evidence: tuple[str, ...]) -> list[str]:
        merge_command = self._evidence_item(evidence, "merge_command")
        merge_readback = self._evidence_item(evidence, "github_merge_readback")
        issue_status = self._evidence_item(evidence, "issue_status_readback")
        parent_completion = self._evidence_item(evidence, "parent_issue_completion_readback")
        branch_cleanup = self._evidence_item(evidence, "branch_cleanup_readback")
        worktree_cleanup = self._evidence_item(evidence, "worktree_cleanup_readback")

        failures: list[str] = []
        # A root-owned exact-head API merge can delete the branch separately.
        # The remote and local deletion readbacks below remain mandatory.
        if not merge_command or not (
            "--delete-branch" in merge_command
            or ("gh api " in merge_command and "/pulls/" in merge_command and "/merge" in merge_command)
        ):
            failures.append("merge_command.merge_invocation")
        if not (
            self._evidence_value(merge_readback, "state").casefold() == "merged"
            or self._evidence_flag(merge_readback, "merged")
        ):
            failures.append("github_merge_readback.merged")
        if not self._evidence_has_value(
            issue_status,
            ("issue_status", "project_status", "status"),
            "Done",
        ):
            failures.append("issue_status_readback.done")
        failures.extend(self._parent_issue_completion_failures(parent_completion))
        if not self._evidence_flag(branch_cleanup, "remote_branch_deleted"):
            failures.append("branch_cleanup_readback.remote_branch_deleted")
        if not self._evidence_flag(branch_cleanup, "local_branch_removed"):
            failures.append("branch_cleanup_readback.local_branch_removed")
        if not self._evidence_flag(worktree_cleanup, "worktree_removed"):
            failures.append("worktree_cleanup_readback.worktree_removed")
        failures.extend(
            self._merged_receipt_failures(
                self._evidence_item(evidence, "process_state_merged"),
            )
        )
        return failures

    def _merged_receipt_failures(self, receipt: str) -> list[str]:
        """process_state_merged evidence를 검증된 receipt와 local history에 결속합니다."""
        merge_commit_oid = self._evidence_value(receipt, "merge_commit_oid")
        pr_number = self._evidence_value(receipt, "pr_number")
        if (
            self._evidence_value(receipt, "state") != "MERGED"
            or re.fullmatch(r"[1-9][0-9]*", pr_number) is None
            or re.fullmatch(r"[0-9a-f]{40}", merge_commit_oid) is None
        ):
            return ["process_state_merged.receipt"]
        if self._repository.head() and not self._repository.contains_commit(merge_commit_oid):
            return ["process_state_merged.merge_commit_readback"]
        return []

    def _parent_issue_completion_failures(self, evidence: str) -> list[str]:
        parent_issue = self._evidence_value(evidence, "parent_issue")
        if parent_issue in {"none", "not_applicable"}:
            return []

        failures: list[str] = []
        if not re.fullmatch(r"#?\d+", parent_issue):
            failures.append("parent_issue_completion_readback.parent_issue")

        all_children_done = self._evidence_value(evidence, "all_child_issues_done").casefold()
        if all_children_done not in {"true", "false"}:
            failures.append("parent_issue_completion_readback.all_child_issues_done")
            return failures

        action = self._evidence_value(evidence, "parent_completion_action")
        if all_children_done == "true":
            if action not in {"updated", "already_done"}:
                failures.append("parent_issue_completion_readback.parent_completion_action")
            if not self._evidence_has_value(
                evidence,
                ("parent_issue_status", "parent_project_status", "project_status", "status"),
                "Done",
            ):
                failures.append("parent_issue_completion_readback.done")
            return failures

        if action != "not_ready":
            failures.append("parent_issue_completion_readback.parent_completion_action")
        if not (
            self._evidence_value(evidence, "remaining_child_issues")
            or self._evidence_value(evidence, "remaining_child_count")
        ):
            failures.append("parent_issue_completion_readback.remaining_child_issues")
        return failures

    def _github_pr_comment_approval_failures(
        self,
        evidence: tuple[str, ...],
        approval: str,
    ) -> list[str]:
        merge_readback = self._evidence_item(evidence, "github_merge_readback")
        author = self._evidence_value(approval, "author")
        pr_author = self._evidence_value(approval, "pr_author")
        approved_head = self._evidence_value(approval, "head_sha")
        current_head = self._evidence_value(merge_readback, "head_sha") or self._evidence_value(
            merge_readback,
            "headRefOid",
        )

        failures: list[str] = []
        for required in ("comment_id", "author", "pr_author", "head_sha", "approved_at"):
            if not self._evidence_value(approval, required):
                failures.append(f"merge_approval.github_pr_comment.{required}")
        if not self._evidence_flag(approval, "merge_intent"):
            failures.append("merge_approval.github_pr_comment.merge_intent")
        if author and pr_author and author.casefold() != pr_author.casefold():
            failures.append("merge_approval.github_pr_comment.pr_author")
        if not current_head:
            failures.append("merge_approval.github_pr_comment.current_head")
        if approved_head and current_head and approved_head != current_head:
            failures.append("merge_approval.github_pr_comment.stale_head")
        return failures

    def _deterministic_enforcement_failures(self, evidence: tuple[str, ...]) -> list[str]:
        # ADR-0023: 산문만으로 원인을 없애는 harness 개선도 정상 경로입니다. gate
        # evidence가 executable 경로를 주장할 때만 그 주장의 모양을 검사하고,
        # prose-only 선언("게이트 없음" 등)은 차단하지 않습니다. 자기선언 문구
        # 받아쓰기 검사(guidance_ack 류)는 사실 검사가 아니므로 두지 않습니다.
        gate = self._evidence_item(evidence, "deterministic_enforcement_gate")

        failures: list[str] = []
        claims_executable = re.search(
            r"(scripts/|\.codex/hooks|\.pre-commit-config\.yaml|uv run python -m scripts\.)",
            gate,
        )
        if claims_executable and not re.search(
            r"(test|tests|unittest|pytest|pre_commit|pre-commit)", gate
        ):
            failures.append("deterministic_enforcement_gate.tested")
        return failures

    def _monitoring_semantic_failures(
        self,
        evidence: tuple[str, ...],
        skill_state: Mapping[str, object],
        *,
        require_local_review: bool = True,
        require_review_matrix: bool = True,
    ) -> list[str]:
        event_source = self._evidence_item(evidence, "monitor_event_source")
        terminal_state = self._evidence_item(evidence, "monitor_terminal_state")
        route_resume = self._evidence_item(evidence, "route_resume_contract")
        monitor_event_readback = self._evidence_item(evidence, "monitor_event_readback")
        live_terminal_readback = self._evidence_item(evidence, "live_terminal_readback")
        ai_review_head_sha = self._evidence_item(evidence, "ai_review_head_sha")
        local_review_head_sha = self._evidence_item(evidence, "local_review_head_sha")
        local_review_matrix_receipt = self._evidence_item(
            evidence,
            "local_review_matrix_receipt",
        )
        pending_comments = self._evidence_item(evidence, "pending_human_comments")
        unresolved_threads = self._evidence_item(evidence, "unresolved_review_threads")

        failures: list[str] = []
        failures.extend(
            self._monitor_subscription_failures(event_source, route_resume, skill_state)
        )
        if "provider=local-pr-monitor" not in event_source:
            failures.append("monitor_event_source.local_background_monitor")
        if "poll_interval_seconds=30" not in event_source:
            failures.append("monitor_event_source.poll_interval_seconds")
        if not re.search(r"resume_adapter=(command|app-server)", event_source):
            failures.append("monitor_event_source.resume_adapter")
        if "monitor_event=terminal" not in terminal_state:
            failures.append("monitor_terminal_state.event_kind")
        if "source=local-pr-monitor" not in terminal_state:
            failures.append("monitor_terminal_state.source")
        acknowledged_terminal = self._acknowledged_active_terminal(
            terminal_state, monitor_event_readback, live_terminal_readback, skill_state
        )
        if not self._resume_invoked(terminal_state) and not acknowledged_terminal:
            failures.append("monitor_terminal_state.resume_status")
        if "provider=local-pr-monitor" not in route_resume:
            failures.append("route_resume_contract.provider")
        if not re.search(r"resume_adapter=(command|app-server)", route_resume):
            failures.append("route_resume_contract.resume_adapter")
        if "source=local-pr-monitor" not in monitor_event_readback:
            failures.append("monitor_event_readback.source")
        if not self._resume_invoked(monitor_event_readback) and not acknowledged_terminal:
            failures.append("monitor_event_readback.resume_status")
        if (
            self._evidence_value(monitor_event_readback, "resume_status") == "pending-delivery"
            and not acknowledged_terminal
        ):
            failures.append("monitor_event_readback.ack")
        terminal_reason = self._evidence_value(terminal_state, "reason")
        live_reason = self._evidence_value(live_terminal_readback, "reason")
        if not live_reason or live_reason != terminal_reason:
            failures.append("live_terminal_readback.reason")
        live_state = self._evidence_value(live_terminal_readback, "state")
        if terminal_reason == "mergeable-clean":
            required_values = {
                "state": "OPEN",
                "mergeState": "CLEAN",
                "reviewDecision": "APPROVED",
                "failedChecks": "0",
                "pendingChecks": "0",
                "unresolvedReviewThreads": "0",
            }
            for key, expected in required_values.items():
                if self._evidence_value(live_terminal_readback, key) != expected:
                    failures.append(f"live_terminal_readback.{key}")
        elif (terminal_reason == "merged" and live_state != "MERGED") or (
            terminal_reason == "closed-without-merge" and live_state != "CLOSED"
        ):
            failures.append("live_terminal_readback.state")
        live_head = self._evidence_value(live_terminal_readback, "headRefOid")
        reviewed_head = self._head_evidence_value(ai_review_head_sha)
        local_reviewed_head = self._head_evidence_value(local_review_head_sha)
        if not reviewed_head:
            failures.append("ai_review_head_sha.current_head")
        if not live_head:
            failures.append("live_terminal_readback.headRefOid")
        elif reviewed_head and live_head != reviewed_head:
            failures.append("live_terminal_readback.head_sha_mismatch")
        if require_local_review:
            if (
                "kind=final-local-review" not in local_review_head_sha
                or "outcome=result-applied" not in local_review_head_sha
                or re.fullmatch(r"[0-9a-f]{40}", local_reviewed_head) is None
            ):
                failures.append("local_review_head_sha.receipt")
            elif live_head and local_reviewed_head != live_head:
                failures.append("local_review_head_sha.remote_head_mismatch")
            if require_review_matrix:
                failures.extend(
                    self._local_review_matrix_receipt_failures(
                        local_review_matrix_receipt,
                        local_reviewed_head,
                    )
                )
        if not re.search(r"\bTOTAL=0\b", pending_comments):
            failures.append("pending_human_comments.total_zero")
        if not re.search(r"\bUNRESOLVED_THREADS_COUNT=0\b", unresolved_threads):
            failures.append("unresolved_review_threads.total_zero")
        return failures

    def _monitor_subscription_failures(
        self,
        event_source: str,
        route_resume: str,
        skill_state: Mapping[str, object],
    ) -> list[str]:
        """Monitoring evidence identity를 durable subscription read-back에 결속합니다."""
        subscription = skill_state.get("monitor_event_subscription")
        if not isinstance(subscription, dict):
            return ["monitor_event_source.subscription_readback"]
        failures: list[str] = []
        legacy_keys = {
            "process_state_path",
            "state_path",
            "thread_id",
            "worktree",
        }.intersection(subscription)
        if legacy_keys:
            failures.append("monitor_event_source.subscription_legacy_path")
        for key in (
            "provider",
            "repo",
            "pr_number",
            "session_id",
            "workflow_id",
            "runtime_id",
            "worktree_id",
            "resume_adapter",
        ):
            expected = subscription.get(key)
            if (
                not isinstance(expected, str | int)
                or isinstance(expected, bool)
                or not str(expected)
            ):
                failures.append(f"monitor_event_source.subscription_{key}")
                continue
            if self._evidence_value(event_source, key) != str(expected):
                failures.append(f"monitor_event_source.{key}_mismatch")
            if self._evidence_value(route_resume, key) != str(expected):
                failures.append(f"route_resume_contract.{key}_mismatch")
        worktree_id = subscription.get("worktree_id")
        observation_resource = subscription.get("observation_resource")
        if not isinstance(observation_resource, dict) or observation_resource != {
            "kind": "monitor-observation-cache",
            "worktree_id": worktree_id,
        }:
            failures.append("monitor_event_source.subscription_observation_resource")
        else:
            expected_resource = f"monitor-observation-cache:{worktree_id}"
            if self._evidence_value(event_source, "observation_resource") != expected_resource:
                failures.append("monitor_event_source.observation_resource_mismatch")
            if self._evidence_value(route_resume, "observation_resource") != expected_resource:
                failures.append("route_resume_contract.observation_resource_mismatch")
        poll_interval = subscription.get("poll_interval_seconds")
        if (
            not isinstance(poll_interval, int)
            or isinstance(poll_interval, bool)
            or poll_interval <= 0
        ):
            failures.append("monitor_event_source.subscription_poll_interval_seconds")
        elif self._evidence_value(event_source, "poll_interval_seconds") != str(poll_interval):
            failures.append("monitor_event_source.poll_interval_seconds_mismatch")
        return failures

    def _resume_invoked(self, evidence: str) -> bool:
        return re.search(r"\bresume_status=invoked(?!-)\b", evidence) is not None

    def _acknowledged_active_terminal(
        self,
        terminal_state: str,
        event_readback: str,
        live_readback: str,
        skill_state: Mapping[str, object],
    ) -> bool:
        """Admit an active owner's merged event only through the typed live ACK."""
        reason = self._evidence_value(terminal_state, "reason")
        if reason not in {"merged", "closed-without-merge"}:
            return False
        if any(
            self._evidence_value(item, "resume_status") != "pending-delivery"
            for item in (terminal_state, event_readback)
        ):
            return False
        event_id = self._evidence_value(event_readback, "event_id")
        if (
            re.fullmatch(r"[0-9a-f]{64}", event_id or "") is None
            or self._evidence_value(terminal_state, "event_id") != event_id
            or self._evidence_value(event_readback, "reason") != reason
        ):
            return False
        acknowledgement = skill_state.get("monitor_event_ack")
        if not isinstance(acknowledgement, Mapping):
            return False
        if acknowledgement.get("event_id") != event_id or acknowledgement.get("reason") != reason:
            return False
        live_state = "MERGED" if reason == "merged" else "CLOSED"
        head = self._evidence_value(live_readback, "headRefOid")
        evidence = acknowledgement.get("evidence")
        return (
            isinstance(evidence, list)
            and all(isinstance(item, str) for item in evidence)
            and self._evidence_value(live_readback, "state") == live_state
            and re.fullmatch(r"[0-9a-f]{40}", head or "") is not None
            and f"terminal_readback:state={live_state}" in evidence
            and f"terminal_readback:headRefOid={head}" in evidence
        )

    def _previous_evidence_item(self, state: PhaseRunState, evidence_key: str) -> str:
        for phase in reversed(state.phases):
            if phase.status == "pending":
                continue
            item = self._evidence_item(phase.evidence, evidence_key)
            if item:
                return item
        return ""

    def _evidence_flag(self, evidence: str, key: str) -> bool:
        return self._evidence_value(evidence, key).lower() == "true"

    def _evidence_value(self, evidence: str, key: str) -> str:
        match = re.search(rf"\b{re.escape(key)}=([^\s,;]+)", evidence)
        if match is None:
            return ""
        return match.group(1)

    def _head_evidence_value(self, evidence: str) -> str:
        """Structured key 또는 evidence value의 첫 token에서 commit SHA를 읽습니다."""
        for key in ("head_sha", "sha"):
            value = self._evidence_value(evidence, key)
            if value:
                return value
        if ":" in evidence:
            tokens = evidence.partition(":")[2].strip().split()
            if tokens:
                return tokens[0]
        return ""

    def _evidence_has_value(self, evidence: str, keys: tuple[str, ...], expected: str) -> bool:
        expected_value = expected.casefold()
        return any(self._evidence_value(evidence, key).casefold() == expected_value for key in keys)

    def _github_metadata_language_failures(self, evidence: tuple[str, ...]) -> list[str]:
        metadata = self._evidence_item(evidence, "github_metadata_language")
        failures: list[str] = []
        required_fragments = (
            "validator=scripts.skill_harness.github_metadata_language",
            "policy_passed=true",
        )
        for fragment in required_fragments:
            if fragment not in metadata:
                failures.append(f"github_metadata_language.{fragment}")
        return failures

    def _evidence_item(self, evidence: tuple[str, ...], evidence_key: str) -> str:
        for item in evidence:
            if evidence_key in item:
                # The named producer retains provenance in the artifact and
                # appends this display trailer. It is not part of JSON/token values.
                return item.removesuffix(" [authority=agent-report]")
        return ""

    def budget_expired(self, state: PhaseRunState) -> bool:
        """Current evaluate-harness run이 emergency wall-clock watchdog을 넘겼는지 반환합니다."""
        return (
            state.skill == "evaluate-harness"
            and state.started_at_epoch is not None
            and max(0.0, time.time() - state.started_at_epoch)
            > EVALUATE_HARNESS_MAX_WALL_CLOCK_SECONDS
        )

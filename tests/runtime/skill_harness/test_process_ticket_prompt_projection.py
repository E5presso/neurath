"""Process-ticket의 phase/rare-route conditional prompt projection을 검증합니다."""

from pathlib import Path
from unittest import TestCase

from scripts.skill_harness.checker import SkillHarnessChecker

ROOT = Path(__file__).resolve().parents[3]
SKILL = ROOT / ".agents/skills/process-ticket/SKILL.md"
INCIDENT_REFERENCE = ROOT / ".agents/skills/process-ticket/references/harness-incident.md"
PHASE_FOUR = ROOT / ".agents/skills/process-ticket/phases/phase-4-review.md"
PHASE_SIX = ROOT / ".agents/skills/process-ticket/phases/phase-6-monitor.md"
PHASE_EIGHT = ROOT / ".agents/skills/process-ticket/phases/phase-8-merge-cleanup.md"
PHASE_RESOURCES = tuple(sorted((SKILL.parent / "phases").glob("*.md")))
BASELINE_ENTRY_BYTES = 22_541
COMPACT_ENTRY_BUDGET_BYTES = 14_000
INCIDENT_COMMAND_PREFIX = "uv run python -m scripts.agent_harness.harness_incident "
INCIDENT_COMMANDS = (
    "uv run python -m scripts.agent_harness.harness_incident record "
    "--id STABLE_RULE_ID --symptom OBSERVED_FAILURE",
    "uv run python -m scripts.agent_harness.harness_incident escalate "
    "--id STABLE_RULE_ID --summary HANDOFF_SUMMARY "
    "--reproduction-command REPRODUCTION_COMMAND",
    "uv run python -m scripts.agent_harness.harness_incident resolve "
    "--id STABLE_RULE_ID --root-cause ROOT_CAUSE "
    "--harness-fix HARNESS_FIX_PATH --regression-command REGRESSION_COMMAND",
    "uv run python -m scripts.agent_harness.harness_incident refresh --id STABLE_OR_OCCURRENCE_ID",
    "uv run python -m scripts.agent_harness.harness_incident refresh "
    "--id OCCURRENCE_ID_ONE --id OCCURRENCE_ID_TWO "
    "--regression-command REGRESSION_COMMAND",
    "uv run python -m scripts.agent_harness.harness_incident supersede "
    "--id OCCURRENCE_ID --harness-fix REPLACEMENT_PATH "
    "--regression-command REGRESSION_COMMAND",
    "uv run python -m scripts.agent_harness.harness_incident validate",
)
INCIDENT_COMMAND_NAMES = frozenset({
    "record",
    "escalate",
    "resolve",
    "refresh",
    "supersede",
    "validate",
})


class ProcessTicketPromptProjectionTest(TestCase):
    """Rare incident detail이 ordinary ticket context를 차지하지 않게 고정합니다."""

    def test_entry_and_each_lazy_route_do_not_exceed_the_previous_entry(self) -> None:
        """Normal route와 각 phase/incident route가 이전 eager entry를 넘지 않습니다."""
        entry_bytes = len(SKILL.read_bytes())

        self.assertLessEqual(entry_bytes, COMPACT_ENTRY_BUDGET_BYTES)
        for resource in (*PHASE_RESOURCES, INCIDENT_REFERENCE):
            with self.subTest(resource=resource):
                self.assertLessEqual(
                    entry_bytes + len(resource.read_bytes()),
                    BASELINE_ENTRY_BYTES,
                )

    def test_entry_keeps_cross_phase_authority_and_failure_kernel(self) -> None:
        """Cross-phase safety와 blocked semantics는 conditional detail로 밀어내지 않습니다."""
        entry = SKILL.read_text(encoding="utf-8")
        required_anchors = (
            "자동 완결",
            "중간 사용자 승인 사유가 아닙니다",
            "사용자의 최종 병합 승인",
            "runtime identity",
            "workflow_id",
            "worktree claim",
            "host-attested `DIRECT_CHILD`",
            "authority가 `UNAVAILABLE`이면 blocked",
            "root, serial, `SAME_SESSION` fallback",
            "사용자 직접 지적",
            "agent가 스스로 인지한",
            "user-reported-harness-defect",
            "rule_id",
            "occurrence_id",
            "미해결 incident는 Stop과 finalize를 차단",
            "GitHub이 merge를 확인하기 전에는 `merged`",
        )

        for anchor in required_anchors:
            with self.subTest(anchor=anchor):
                self.assertIn(anchor, entry)

    def test_stateful_incident_commands_live_exactly_once_in_the_conditional_reference(
        self,
    ) -> None:
        """Canonical incident command는 conditional owner에만 exactly once 남습니다."""
        entry = SKILL.read_text(encoding="utf-8")
        reference = INCIDENT_REFERENCE.read_text(encoding="utf-8")

        for command in INCIDENT_COMMANDS:
            with self.subTest(command=command):
                self.assertNotIn(command, entry)
                self.assertEqual(1, reference.count(command))

        checker = SkillHarnessChecker(ROOT)
        observed_commands = tuple(
            fragment
            for fragment in checker._stateful_markdown_fragments(entry)
            if fragment.startswith(INCIDENT_COMMAND_PREFIX)
        )
        reference_commands = tuple(
            fragment
            for fragment in checker._stateful_markdown_fragments(reference)
            if fragment.startswith(INCIDENT_COMMAND_PREFIX)
        )
        self.assertEqual((), observed_commands)
        self.assertCountEqual(INCIDENT_COMMANDS, reference_commands)
        observed_names = frozenset(
            command.removeprefix(INCIDENT_COMMAND_PREFIX).split(maxsplit=1)[0]
            for command in reference_commands
        )
        self.assertEqual(INCIDENT_COMMAND_NAMES, observed_names)

    def test_reference_is_reachable_only_for_detected_incident_detail(self) -> None:
        """양 runtime이 selected SKILL의 exact pointer로 detail을 발견합니다."""
        entry = SKILL.read_text(encoding="utf-8")
        reachable = SkillHarnessChecker(ROOT)._reachable_resources(SKILL)

        self.assertEqual(1, entry.count("references/harness-incident.md"))
        self.assertIn("incident를 처리해야 할 때만", entry)
        self.assertIn(INCIDENT_REFERENCE.resolve(), reachable)

    def test_reference_retains_every_incident_authority_and_recovery_capability(self) -> None:
        """Conditional detail은 typed incident authority와 recovery를 빠뜨리지 않습니다."""
        reference = INCIDENT_REFERENCE.read_text(encoding="utf-8")
        capability_anchors = (
            "StateHandle.attach",
            "session-level typed occurrence",
            "수정 소유권",
            "loop owner",
            "execution_trajectory",
            "turn_harness_audit",
            "review_acceptance_matrix",
            "stable finding key",
            "root_cause_deduplication",
            "structured command receipt",
            "exit code 0을 재검증",
            "current HEAD",
            "ancestor",
            "clean",
            "executable",
            "allowlist",
            "batch refresh",
            "여러 occurrence",
            "evidence_refreshed_at",
            "superseded_resolution_evidence",
            "raw state",
        )

        for anchor in capability_anchors:
            with self.subTest(anchor=anchor):
                self.assertIn(anchor, reference)

    def test_phase_resources_own_delegation_monitor_and_terminal_detail(self) -> None:
        """Phase-specific authority는 해당 phase에서만 읽히고 capability를 보존합니다."""
        entry = SKILL.read_text(encoding="utf-8")
        phase_four = PHASE_FOUR.read_text(encoding="utf-8")
        phase_six = PHASE_SIX.read_text(encoding="utf-8")
        phase_eight = PHASE_EIGHT.read_text(encoding="utf-8")

        self.assertNotIn("status: merged|mergeable-clean|failed|skipped|blocked", entry)
        self.assertIn("status: merged|mergeable-clean|failed|skipped|blocked", phase_eight)
        self.assertIn("이 파일의 `Canonical terminal report`", phase_eight)

        for anchor in (
            "StateHandle.attach",
            "hook_agent_id == target_agent_id",
            "session-local content-addressed artifact",
            "execution_trajectory",
            "turn_harness_audit",
        ):
            with self.subTest(phase="four", anchor=anchor):
                self.assertIn(anchor, phase_four)
        for anchor in (
            "owner_lifecycle",
            "monitor_mailbox",
            "delegate-result-ready",
            "final-local-review",
            "route_resume_contract",
            "monitor_event_readback",
            "pending_human_comments",
        ):
            with self.subTest(phase="six", anchor=anchor):
                self.assertIn(anchor, phase_six)
        for anchor in (
            "merge_cleanup.py --workflow-id",
            "parent_issue_completion_readback",
            "terminal report",
            "gaps_detected",
            "gaps_dispatched",
            "acceptance_check",
            "review_done",
            "`review_done: skipped`와 사유를 `notes`에 기록합니다",
            "`failed_reason`은 `status: failed`에서만 필수입니다",
        ):
            with self.subTest(phase="eight", anchor=anchor):
                self.assertIn(anchor, phase_eight)

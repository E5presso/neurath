"""An exact merged-event ACK can terminalize a root-owned autopilot merge."""

import json
import re
from pathlib import Path

from neurath.resources import BUNDLE
from scripts.skill_harness.phase_evidence_validation import PhaseEvidenceValidator


ROOT = Path(__file__).resolve().parents[3]
HEAD = "a" * 40
EVENT = "b" * 64


def evidence():
    identity = (
        "provider=local-pr-monitor repo=octo/neurath pr_number=117 "
        "session_id=worker workflow_id=ticket runtime_id=monitor-1 "
        "worktree_id=issue-117 observation_resource=monitor-observation-cache:issue-117 "
        "resume_adapter=app-server"
    )
    terminal = (
        f"monitor_event=terminal reason=merged source=local-pr-monitor "
        f"resume_status=pending-delivery event_id={EVENT}"
    )
    return (
        f"monitor_event_source: {identity} poll_interval_seconds=30",
        f"monitor_terminal_state: {terminal}",
        f"route_resume_contract: {identity}",
        f"monitor_event_readback: {terminal}",
        f"live_terminal_readback: reason=merged state=MERGED headRefOid={HEAD} unresolvedReviewThreads=0",
        f"ai_review_head_sha: head_sha={HEAD}",
        "pending_human_comments: TOTAL=0",
        "unresolved_review_threads: UNRESOLVED_THREADS_COUNT=0",
    )


def skill_state(event_id=EVENT, head=HEAD):
    return {
        "monitor_event_subscription": {
            "provider": "local-pr-monitor",
            "repo": "octo/neurath",
            "pr_number": 117,
            "session_id": "worker",
            "workflow_id": "ticket",
            "runtime_id": "monitor-1",
            "worktree_id": "issue-117",
            "observation_resource": {
                "kind": "monitor-observation-cache", "worktree_id": "issue-117"
            },
            "poll_interval_seconds": 30,
            "resume_adapter": "app-server",
        },
        "monitor_event_ack": {
            "event_id": event_id,
            "reason": "merged",
            "evidence": [
                "terminal_readback:state=MERGED",
                f"terminal_readback:headRefOid={head}",
            ],
            "acknowledged_at": "2026-09-30T00:00:00Z",
        },
    }


def test_active_owner_can_finish_acknowledged_root_merge_without_fake_resume():
    current = evidence()
    contracts = json.loads((BUNDLE / ".agents/skills/contracts.json").read_text())
    monitoring = next(
        item for item in contracts["skills"]["process-ticket"]["phase_contracts"]
        if item["name"] == "monitoring"
    )
    pattern = monitoring["evidence_patterns"]["monitor_event_readback"]

    assert re.search(pattern, current[3])
    assert PhaseEvidenceValidator(ROOT)._monitoring_semantic_failures(
        current, skill_state(), require_local_review=False, require_review_matrix=False
    ) == []


def test_active_owner_merge_requires_the_exact_event_and_head_ack():
    validator = PhaseEvidenceValidator(ROOT)
    no_ack = skill_state()
    del no_ack["monitor_event_ack"]
    for stale in (no_ack, skill_state(event_id="c" * 64), skill_state(head="d" * 40)):
        failures = validator._monitoring_semantic_failures(
            evidence(), stale, require_local_review=False, require_review_matrix=False
        )
        assert "monitor_event_readback.ack" in failures

"""Exact-head review publisher의 session-scoped canonical evidence 계약입니다."""

import hashlib
import importlib.util
import inspect
import json
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from scripts.agent_harness.artifact_store import SessionArtifactStore
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
    SessionLocator,
    WorkflowId,
    WorkflowStarted,
)
from scripts.agent_harness.state_handle import (
    RuntimeEnvironmentResolver,
    RuntimeIdentityBinding,
    StateHandle,
)

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / ".agents/skills/pr-review/scripts/publish_final_review.py"
SPEC = importlib.util.spec_from_file_location("publish_final_review", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

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


class PublisherFixture:
    """Temporary repository와 canonical workflow/delegation evidence를 소유합니다."""

    def __init__(self, *, consumed: bool = True) -> None:
        """Exact session, workflow, final review artifact를 준비합니다."""
        self._directory = TemporaryDirectory()
        self.worktree = Path(self._directory.name)
        self._git("init", "-b", "develop")
        self._git("config", "user.email", "test@example.invalid")
        self._git("config", "user.name", "Neurath Publisher Test")
        (self.worktree / ".gitignore").write_text(
            ".agents/runs/\n.process-state.json\n",
            encoding="utf-8",
        )
        (self.worktree / "review.txt").write_text("reviewed\n", encoding="utf-8")
        self._git("add", ".gitignore", "review.txt")
        self._git("commit", "--no-verify", "-m", "reviewed head")
        self.head = self._git("rev-parse", "HEAD")

        self.session_id = "publisher-session"
        self.workflow_id = WorkflowId("process-ticket-131")
        self.reviewer_id = ActorId("codex:final-reviewer")
        self.locator = SessionLocator.from_worktree(self.worktree)
        self.root_binding = RuntimeEnvironmentResolver().resolve({
            "CODEX_THREAD_ID": self.session_id,
        })
        self.root_handle = StateHandle.initialize(self.locator, self.root_binding)
        self.root_handle.apply(
            WorkflowStarted(
                session_id=self.root_handle.session_id,
                workflow_id=self.workflow_id,
                owner_actor_id=self.root_handle.actor_id,
                kind="process-ticket",
                goal="PR #131 exact-head publication",
                payload={
                    "phase_run": {"phase": 6},
                    "skill_state": self._skill_state(),
                },
                idempotency_key="publisher-workflow-started",
            )
        )
        self.root_handle.apply(
            ActorStarted(
                session_id=self.root_handle.session_id,
                actor_id=self.reviewer_id,
                parent_actor_id=self.root_handle.actor_id,
                kind=ActorKind.SUBAGENT,
                idempotency_key="publisher-reviewer-started",
                lineage_assurance=ActorLineageAssurance.HOST_ATTESTED,
            )
        )
        self.delegation_id = DelegationId("final-review-131")
        matrix = self._matrix()
        assignment = json.dumps(
            {
                "kind": "final-local-review",
                "review_acceptance_matrix": matrix,
                "reviewed_head_sha": self.head,
                "scope": "exact-head read-only review",
                "started_at": "2026-08-04T00:00:00+00:00",
                "target": "final reviewer",
                "workflow_id": str(self.workflow_id),
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        self.root_handle.apply(
            DelegationAssigned(
                session_id=self.root_handle.session_id,
                delegation_id=self.delegation_id,
                owner_actor_id=self.root_handle.actor_id,
                target_actor_id=self.reviewer_id,
                assignment=assignment,
                idempotency_key="publisher-review-assigned",
                topology_policy=DelegationTopologyPolicy.DIRECT_CHILD,
            )
        )
        self.outcome_ref = self._report_review(matrix, consumed=consumed)

    def cleanup(self) -> None:
        """Temporary repository와 session state를 제거합니다."""
        self._directory.cleanup()

    def valid_pr(self) -> dict[str, object]:
        """Canonical route와 일치하는 live PR metadata를 만듭니다."""
        return {
            "number": 131,
            "state": "OPEN",
            "isDraft": False,
            "isCrossRepository": False,
            "headRefOid": self.head,
            "url": "https://github.com/E5presso/neurath/pull/131",
        }

    def environment(self, *, session_id: str | None = None) -> dict[str, str]:
        """Inherited runtime identity를 제거한 exact Codex environment를 만듭니다."""
        environment = dict(os.environ)
        for key in (
            "CLAUDE_CODE_SESSION_ID",
            "CODEX_THREAD_ID",
            "NEURATH_AGENT_SESSION_ID",
            "NEURATH_AGENT_ACTOR_ID",
            "NEURATH_AGENT_RUNTIME",
        ):
            environment.pop(key, None)
        environment["CODEX_THREAD_ID"] = self.session_id if session_id is None else session_id
        current_python_path = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = (
            str(ROOT) if not current_python_path else f"{ROOT}{os.pathsep}{current_python_path}"
        )
        return environment

    def artifact_path(self) -> Path:
        """Corruption test가 exact review artifact 한 개를 찾도록 canonical path를 반환합니다."""
        digest = self.outcome_ref.removeprefix("sha256:")
        return (
            self.locator.locate(self.root_handle.session_id).artifacts / "sha256" / f"{digest}.json"
        )

    def _skill_state(self) -> dict[str, object]:
        return {
            "commit_done": {"sha": self.head},
            "harness_incidents": [],
            "monitor_event_subscription": {
                "repo": "E5presso/neurath",
                "pr_number": 131,
            },
            "pr_opened": {
                "number": 131,
                "url": "https://github.com/E5presso/neurath/pull/131",
                "head_sha": self.head,
            },
            "push_done": {"local_sha": self.head, "remote_sha": self.head},
        }

    def _matrix(self) -> dict[str, object]:
        rows = [
            {"category": category, "row_id": row_id, "severity": severity}
            for row_id, category, severity in REVIEW_ROWS
        ]
        identity = json.dumps(
            {"head_sha": self.head, "rows": rows},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return {
            "frozen": True,
            "head_sha": self.head,
            "matrix_id": hashlib.sha256(identity.encode()).hexdigest(),
            "row_count": len(rows),
            "rows": rows,
        }

    def _report_review(self, matrix: dict[str, object], *, consumed: bool) -> str:
        reviewer_binding = RuntimeIdentityBinding(
            runtime=self.root_binding.runtime,
            session_id=self.root_handle.session_id,
            actor_id=self.reviewer_id,
            root_actor_id=self.root_handle.actor_id,
        )
        reviewer_handle = StateHandle.attach(self.locator, reviewer_binding)
        rows = [row_id for row_id, _category, _severity in REVIEW_ROWS]
        report = {
            "blocking_findings": [],
            "harness_audit": {
                "checked": True,
                "evidence": [
                    "git_diff:sha256:" + "1" * 64,
                    "process_state:sha256:" + "2" * 64,
                    "execution_trajectory:sha256:" + "3" * 64,
                ],
            },
            "inherited_from_head": None,
            "inherited_review_rows": [],
            "matrix_head_sha": self.head,
            "matrix_id": matrix["matrix_id"],
            "review_findings": [],
            "review_notes": [],
            "reverified_review_rows": rows,
            "summary": "독립 리뷰가 blocker 없이 통과했습니다.",
            "verified_review_rows": rows,
            "verdict": "pass",
        }
        artifact = SessionArtifactStore(reviewer_handle).put_json({
            "delegation_id": str(self.delegation_id),
            "report": report,
            "schema": "neurath.delegation-result.v1",
            "target_agent_id": str(self.reviewer_id),
        })
        reviewer_handle.apply(
            DelegationReported(
                session_id=reviewer_handle.session_id,
                delegation_id=self.delegation_id,
                reporter_actor_id=self.reviewer_id,
                result=DelegationResult(
                    verdict="pass",
                    summary=report["summary"],
                    outcome_ref=artifact.reference,
                    blocking_findings=(),
                ),
                idempotency_key="publisher-review-reported",
            )
        )
        if consumed:
            self.root_handle.apply(
                DelegationConsumed(
                    session_id=self.root_handle.session_id,
                    delegation_id=self.delegation_id,
                    consumer_actor_id=self.root_handle.actor_id,
                    idempotency_key="publisher-review-consumed",
                )
            )
        return artifact.reference

    def _git(self, *arguments: str) -> str:
        completed = subprocess.run(
            ("git", "-C", str(self.worktree), *arguments),
            check=True,
            capture_output=True,
            text=True,
        )
        return completed.stdout.strip()


class PublishFinalReviewTest(TestCase):
    """Publisher가 exact workflow와 consumed artifact만 승인 증거로 쓰는지 검증합니다."""

    def fixture(self, *, consumed: bool = True) -> PublisherFixture:
        """Cleanup이 등록된 publisher fixture를 생성합니다."""
        fixture = PublisherFixture(consumed=consumed)
        self.addCleanup(fixture.cleanup)
        return fixture

    def test_reads_consumed_final_review_from_one_canonical_session_snapshot(self) -> None:
        """Workflow evidence와 consumed delegation/artifact가 일치하면 receipt를 만듭니다."""
        fixture = self.fixture()
        snapshot = MODULE.CanonicalPublicationEvidenceReader(
            fixture.root_handle,
            fixture.workflow_id,
        ).read(local_head=fixture.head)

        policy = MODULE.PublicationPolicy()
        receipt = policy.validate(
            snapshot=snapshot,
            pr=fixture.valid_pr(),
            local_head=fixture.head,
        )

        self.assertEqual(fixture.head, receipt.head_sha)
        self.assertEqual(fixture.outcome_ref, receipt.outcome_ref)
        self.assertTrue(
            policy.build_comment(receipt).endswith(
                f"<!-- ai-review verdict=AUTO_APPROVE head={fixture.head} -->"
            )
        )

    def test_rejects_reported_but_unconsumed_final_review(self) -> None:
        """Owner가 consume하지 않은 target report는 publication authority가 아닙니다."""
        fixture = self.fixture(consumed=False)

        with self.assertRaisesRegex(MODULE.DelegationEvidenceError, "consumed"):
            MODULE.CanonicalPublicationEvidenceReader(
                fixture.root_handle,
                fixture.workflow_id,
            ).read(local_head=fixture.head)

    def test_rejects_tampered_digest_verified_review_artifact(self) -> None:
        """Typed result가 가리키는 artifact bytes가 바뀌면 publication을 차단합니다."""
        fixture = self.fixture()
        fixture.artifact_path().write_text('{"tampered":true}', encoding="utf-8")

        with self.assertRaisesRegex(Exception, "digest mismatch"):
            MODULE.CanonicalPublicationEvidenceReader(
                fixture.root_handle,
                fixture.workflow_id,
            ).read(local_head=fixture.head)

    def test_rejects_stale_remote_head_and_different_pr_identity(self) -> None:
        """Remote head 또는 canonical PR route가 다르면 동일 review도 게시하지 않습니다."""
        fixture = self.fixture()
        snapshot = MODULE.CanonicalPublicationEvidenceReader(
            fixture.root_handle,
            fixture.workflow_id,
        ).read(local_head=fixture.head)
        stale = fixture.valid_pr()
        stale["headRefOid"] = "4" * 40
        with self.assertRaisesRegex(MODULE.PublicationError, "SHA가 일치하지 않습니다"):
            MODULE.PublicationPolicy().validate(
                snapshot=snapshot,
                pr=stale,
                local_head=fixture.head,
            )

        other_pr = fixture.valid_pr()
        other_pr["number"] = 999
        with self.assertRaisesRegex(MODULE.PublicationError, "PR identity"):
            MODULE.PublicationPolicy().validate(
                snapshot=snapshot,
                pr=other_pr,
                local_head=fixture.head,
            )

    def test_public_api_has_workflow_identity_and_no_state_path_selector(self) -> None:
        """Publisher API는 exact handle/workflow를 받고 caller-selected state path를 받지 않습니다."""
        parameters = inspect.signature(MODULE.FinalReviewPublisher).parameters

        self.assertIn("handle", parameters)
        self.assertIn("workflow_id", parameters)
        self.assertNotIn("state_path", parameters)
        self.assertNotIn("path", parameters)

    def test_cli_fails_closed_for_unknown_session_without_reading_legacy_state(self) -> None:
        """Runtime session이 다르면 같은 CWD의 legacy JSON으로 fallback하지 않습니다."""
        fixture = self.fixture()
        legacy = fixture.worktree / ".process-state.json"
        legacy.write_text(json.dumps(fixture._skill_state()), encoding="utf-8")

        completed = subprocess.run(
            (
                sys.executable,
                str(SCRIPT),
                "--workflow-id",
                str(fixture.workflow_id),
                "--repo",
                "E5presso/neurath",
                "--pr-number",
                "131",
            ),
            cwd=fixture.worktree,
            env=fixture.environment(session_id="unknown-session"),
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(1, completed.returncode)
        self.assertIn("state is missing", completed.stdout.lower())
        self.assertTrue(legacy.is_file())

    def test_cli_rejects_legacy_state_argument(self) -> None:
        """Public CLI는 --state를 compatibility alias로 남기지 않습니다."""
        fixture = self.fixture()

        completed = subprocess.run(
            (
                sys.executable,
                str(SCRIPT),
                "--workflow-id",
                str(fixture.workflow_id),
                "--state",
                ".process-state.json",
                "--pr-number",
                "131",
            ),
            cwd=fixture.worktree,
            env=fixture.environment(),
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(2, completed.returncode)
        self.assertIn("unrecognized arguments", completed.stderr)

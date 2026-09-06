"""Process-ticket delegation CLI의 session-scoped typed state 계약을 검증합니다."""

import json
import os
import subprocess
import sys
from collections.abc import Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

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
    DelegationStatus,
    DelegationTopologyPolicy,
    ProcessState,
    SessionId,
    SessionKernel,
    SessionLocator,
    WorkflowId,
    WorkflowStarted,
)
from scripts.agent_harness.state_handle import RuntimeEnvironmentResolver, StateHandle

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / ".agents/skills/process-ticket/scripts/delegate_state.py"
REVIEW_ROW_IDS = tuple(f"C{index:02d}" for index in range(1, 15))


class DelegateCliFixture:
    """Temporary Git worktree와 exact SessionKernel workflow를 함께 소유합니다."""

    def __init__(self) -> None:
        """Root actor와 process-ticket workflow가 있는 isolated control plane을 만듭니다."""
        self._directory = TemporaryDirectory()
        self.worktree = Path(self._directory.name)
        self._run_git("init", "-b", "develop")
        self.locator = SessionLocator.from_worktree(self.worktree)
        self.session_id = "delegate-session"
        self.workflow_id = WorkflowId("process-ticket-42")
        self.root_actor_id = ActorId(f"codex:session:{self.session_id}")
        self._resolver = RuntimeEnvironmentResolver()
        root_binding = self._resolver.resolve({"CODEX_THREAD_ID": self.session_id})
        self.root_handle = StateHandle.initialize(self.locator, root_binding)
        self.root_handle.apply(
            WorkflowStarted(
                session_id=self.root_handle.session_id,
                workflow_id=self.workflow_id,
                owner_actor_id=self.root_handle.actor_id,
                kind="process-ticket",
                goal="Issue #42를 완료한다",
                payload={
                    "phase_run": {"phase": 4},
                    "skill_state": {"owner_state": "must-remain-unchanged"},
                },
                idempotency_key="workflow-started:process-ticket-42",
            )
        )

    def cleanup(self) -> None:
        """Temporary repository와 canonical session files를 제거합니다."""
        self._directory.cleanup()

    @property
    def legacy_state_path(self) -> Path:
        """새 CLI가 생성하거나 읽으면 안 되는 worktree-local legacy path입니다."""
        return self.worktree / ".process-state.json"

    @property
    def artifact_files(self) -> tuple[Path, ...]:
        """Exact session artifact directory에 저장된 immutable file을 반환합니다."""
        artifacts = self.locator.locate(self.root_handle.session_id).artifacts
        if not artifacts.exists():
            return ()
        return tuple(path for path in artifacts.rglob("*.json") if path.is_file())

    def start_actor(self, actor_id: ActorId) -> None:
        """Root authority로 submit target subagent를 session topology에 등록합니다."""
        self.root_handle.apply(
            ActorStarted(
                session_id=self.root_handle.session_id,
                actor_id=actor_id,
                parent_actor_id=self.root_handle.actor_id,
                kind=ActorKind.SUBAGENT,
                idempotency_key=f"actor-started:{actor_id}",
                lineage_assurance=ActorLineageAssurance.HOST_ATTESTED,
            )
        )

    def run_cli(
        self,
        *arguments: str,
        actor_id: ActorId | None = None,
        session_id: str | None = None,
        workflow_id: WorkflowId | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """CWD와 runtime environment만으로 delegate CLI를 실행합니다."""
        runtime_session = self.session_id if session_id is None else session_id
        runtime_workflow = self.workflow_id if workflow_id is None else workflow_id
        environment = {
            **os.environ,
            "PYTHONPATH": str(ROOT),
            "CODEX_THREAD_ID": runtime_session,
        }
        if actor_id is not None:
            environment.update({
                "NEURATH_AGENT_SESSION_ID": runtime_session,
                "NEURATH_AGENT_ACTOR_ID": str(actor_id),
                "NEURATH_AGENT_RUNTIME": "codex",
            })
        return subprocess.run(
            (
                sys.executable,
                str(SCRIPT),
                "--workflow-id",
                str(runtime_workflow),
                *arguments,
            ),
            cwd=self.worktree,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

    def begin(
        self,
        target_actor_id: ActorId,
        *,
        kind: str = "pr-review",
        reviewed_head_sha: str | None = None,
    ) -> dict[str, object]:
        """Registered target에 exact delegation assignment를 시작합니다."""
        arguments = [
            "begin",
            "--kind",
            kind,
            "--target",
            "reviewer",
            "--scope",
            "exact-head read-only review",
            "--target-agent-id",
            str(target_actor_id),
        ]
        if reviewed_head_sha is not None:
            arguments.extend(("--reviewed-head-sha", reviewed_head_sha))
        completed = self.run_cli(*arguments)
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr)
        payload = json.loads(completed.stdout)
        if not isinstance(payload, dict):
            raise TypeError("begin output must be an object")
        return payload

    def submit(
        self,
        begun: Mapping[str, object],
        target_actor_id: ActorId,
        *,
        verdict: str = "pass",
        summary: str = "독립 리뷰가 blocker 없이 통과했습니다.",
        extra_arguments: Iterable[str] = (),
    ) -> subprocess.CompletedProcess[str]:
        """Exact target runtime identity로 structured result를 제출합니다."""
        return self.run_cli(
            "submit",
            "--delegation-id",
            str(begun["delegation_id"]),
            "--target-agent-id",
            str(target_actor_id),
            "--verdict",
            verdict,
            "--summary",
            summary,
            *tuple(extra_arguments),
            actor_id=target_actor_id,
        )

    def complete(
        self,
        begun: Mapping[str, object],
        submitted: Mapping[str, object],
    ) -> subprocess.CompletedProcess[str]:
        """Root owner로 exact reported result를 consume합니다."""
        return self.run_cli(
            "complete",
            "--delegation-id",
            str(begun["delegation_id"]),
            "--target-agent-id",
            str(begun["target_agent_id"]),
            "--outcome-ref",
            str(submitted["outcome_ref"]),
        )

    def inspect(self) -> ProcessState:
        """Exact session의 latest canonical process state를 읽습니다."""
        return SessionKernel(self.locator).inspect(self.root_handle.session_id)

    def consume_generic(self, target: ActorId, assignment: str) -> DelegationId:
        """Generic state API가 허용하는 assignment를 원래 lifecycle로 소비합니다."""
        identifier = DelegationId(f"generic-{len(self.inspect().delegations)}")
        self.root_handle.apply(DelegationAssigned(
            session_id=self.root_handle.session_id,
            delegation_id=identifier,
            owner_actor_id=self.root_actor_id,
            target_actor_id=target,
            assignment=assignment,
            idempotency_key=f"assign:{identifier}",
            topology_policy=DelegationTopologyPolicy.DIRECT_CHILD,
        ))
        binding = self._resolver.resolve({
            "CODEX_THREAD_ID": self.session_id,
            "NEURATH_AGENT_SESSION_ID": self.session_id,
            "NEURATH_AGENT_ACTOR_ID": str(target),
            "NEURATH_AGENT_RUNTIME": "codex",
        })
        child = StateHandle.attach(self.locator, binding)
        child.apply(DelegationReported(
            session_id=child.session_id,
            delegation_id=identifier,
            reporter_actor_id=target,
            result=DelegationResult("pass", "Generic report", "generic-report", ()),
            idempotency_key=f"report:{identifier}",
        ))
        self.root_handle.apply(DelegationConsumed(
            session_id=self.root_handle.session_id,
            delegation_id=identifier,
            consumer_actor_id=self.root_actor_id,
            idempotency_key=f"consume:{identifier}",
        ))
        return identifier

    def workflow_snapshot(self) -> tuple[int, Mapping[str, object]]:
        """Workflow-local revision과 detached payload를 split-commit 검증용으로 반환합니다."""
        workflow = self.root_handle.inspect().workflows[self.workflow_id]
        return workflow.revision, dict(workflow.payload)

    def create_review_heads(self) -> tuple[str, str]:
        """Delta inheritance가 검증할 조상 관계의 두 exact commit을 생성합니다."""
        self._run_git("config", "user.email", "test@example.invalid")
        self._run_git("config", "user.name", "Neurath Delegate Test")
        (self.worktree / "review.txt").write_text("first\n", encoding="utf-8")
        self._run_git("add", "review.txt")
        self._run_git("commit", "--no-verify", "-m", "first review head")
        first_head = self._run_git("rev-parse", "HEAD")
        (self.worktree / "review.txt").write_text("second\n", encoding="utf-8")
        self._run_git("add", "review.txt")
        self._run_git("commit", "--no-verify", "-m", "second review head")
        return first_head, self._run_git("rev-parse", "HEAD")

    def _run_git(self, *arguments: str) -> str:
        completed = subprocess.run(
            ("git", "-C", str(self.worktree), *arguments),
            check=True,
            capture_output=True,
            text=True,
        )
        return completed.stdout.strip()


class DelegateStateTest(TestCase):
    """Delegation identity, lifecycle, artifact, review payload invariant를 검증합니다."""

    def _fixture(self) -> DelegateCliFixture:
        """각 test에 독립적인 exact session fixture를 제공합니다."""
        fixture = DelegateCliFixture()
        self.addCleanup(fixture.cleanup)
        return fixture

    def test_cli_requires_workflow_id_and_rejects_manual_state_selector(self) -> None:
        """Public CLI는 workflow identity를 요구하고 --state/path 우회를 노출하지 않습니다."""
        fixture = self._fixture()
        environment = {**os.environ, "PYTHONPATH": str(ROOT)}
        missing_workflow = subprocess.run(
            (
                sys.executable,
                str(SCRIPT),
                "begin",
                "--kind",
                "pr-review",
                "--target",
                "reviewer",
                "--scope",
                "review",
                "--target-agent-id",
                "codex:reviewer",
            ),
            cwd=fixture.worktree,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        manual_path = subprocess.run(
            (
                sys.executable,
                str(SCRIPT),
                "--state",
                str(fixture.legacy_state_path),
                "--workflow-id",
                str(fixture.workflow_id),
                "begin",
                "--help",
            ),
            cwd=fixture.worktree,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        help_result = subprocess.run(
            (sys.executable, str(SCRIPT), "--help"),
            cwd=fixture.worktree,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertNotEqual(0, missing_workflow.returncode)
        self.assertIn("--workflow-id", missing_workflow.stderr)
        self.assertNotEqual(0, manual_path.returncode)
        self.assertEqual(0, help_result.returncode)
        self.assertNotIn("--state", help_result.stdout)

    def test_delegation_path_has_no_workflow_review_projection_split_commit(self) -> None:
        """Production path는 review lifecycle의 별도 workflow projection을 참조하지 않습니다."""
        source = SCRIPT.read_text(encoding="utf-8")

        for forbidden in (
            "SkillStateStore",
            "ReviewStateMutation",
            "WorkflowReviewReader",
            "ReviewMutationKind",
        ):
            self.assertNotIn(forbidden, source)
        self.assertIn("StateHandle.attach(locator, binding)", source)

    def test_begin_uses_exact_registered_actor_and_typed_assignment(self) -> None:
        """Begin은 runtime session의 registered target에 typed pending assignment를 만듭니다."""
        fixture = self._fixture()
        target_actor_id = ActorId("codex:reviewer-a")
        fixture.start_actor(target_actor_id)

        begun = fixture.begin(target_actor_id)
        state = fixture.inspect()
        delegation = state.delegations[DelegationId(str(begun["delegation_id"]))]

        self.assertEqual(DelegationStatus.PENDING, delegation.status)
        self.assertEqual(fixture.root_actor_id, delegation.owner_actor_id)
        self.assertEqual(target_actor_id, delegation.target_actor_id)
        self.assertEqual(fixture.session_id, begun["owner_session_id"])
        self.assertEqual(str(fixture.root_actor_id), begun["owner_actor_id"])
        assignment = json.loads(delegation.assignment)
        self.assertEqual("pr-review", assignment["kind"])
        self.assertEqual("exact-head read-only review", assignment["scope"])
        self.assertEqual(str(fixture.workflow_id), assignment["workflow_id"])
        self.assertFalse(fixture.legacy_state_path.exists())

    def test_delegation_rejects_another_active_workflow_in_the_same_session(self) -> None:
        """Self-contained assignment은 같은 session의 다른 active workflow로 우회되지 않습니다."""
        fixture = self._fixture()
        target_actor_id = ActorId("codex:reviewer")
        fixture.start_actor(target_actor_id)
        begun = fixture.begin(target_actor_id)
        other_workflow_id = WorkflowId("process-ticket-other")
        fixture.root_handle.apply(
            WorkflowStarted(
                session_id=fixture.root_handle.session_id,
                workflow_id=other_workflow_id,
                owner_actor_id=fixture.root_handle.actor_id,
                kind="process-ticket",
                goal="다른 issue를 처리한다",
                payload={"skill_state": {}},
                idempotency_key="workflow-started:process-ticket-other",
            )
        )

        wrong_workflow = fixture.run_cli(
            "submit",
            "--delegation-id",
            str(begun["delegation_id"]),
            "--target-agent-id",
            str(target_actor_id),
            "--verdict",
            "pass",
            "--summary",
            "잘못된 workflow에서 제출합니다.",
            actor_id=target_actor_id,
            workflow_id=other_workflow_id,
        )

        self.assertNotEqual(0, wrong_workflow.returncode)
        self.assertIn("workflow identity mismatch", wrong_workflow.stderr)
        delegation = fixture.inspect().delegations[DelegationId(str(begun["delegation_id"]))]
        self.assertEqual(DelegationStatus.PENDING, delegation.status)

    def test_begin_rejects_unregistered_or_cross_session_target(self) -> None:
        """Actor topology나 exact session 밖 target을 임의 등록하거나 fallback하지 않습니다."""
        fixture = self._fixture()
        missing_target = fixture.run_cli(
            "begin",
            "--kind",
            "pr-review",
            "--target",
            "reviewer",
            "--scope",
            "review",
            "--target-agent-id",
            "codex:missing",
        )
        wrong_session = fixture.run_cli(
            "begin",
            "--kind",
            "pr-review",
            "--target",
            "reviewer",
            "--scope",
            "review",
            "--target-agent-id",
            "codex:missing",
            session_id="different-session",
        )

        self.assertNotEqual(0, missing_target.returncode)
        self.assertIn("unavailable", missing_target.stderr)
        self.assertNotEqual(0, wrong_session.returncode)
        self.assertIn("session state is missing", wrong_session.stderr)
        self.assertFalse(
            fixture.locator.locate(SessionId("different-session")).process_state.exists()
        )
        self.assertEqual({}, fixture.inspect().delegations)

    def test_concurrent_assignments_preserve_both_delegation_identities(self) -> None:
        """Concurrent subagents는 singleton pending slot 없이 독립 typed records로 공존합니다."""
        fixture = self._fixture()
        targets = (ActorId("codex:reviewer-a"), ActorId("codex:reviewer-b"))
        for target in targets:
            fixture.start_actor(target)

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = tuple(executor.map(fixture.begin, targets))

        state = fixture.inspect()
        self.assertEqual(2, len(state.delegations))
        self.assertEqual(2, len({result["delegation_id"] for result in results}))
        self.assertEqual(
            set(targets), {item.target_actor_id for item in state.delegations.values()}
        )

    def test_concurrent_review_assignments_are_self_contained_without_workflow_mutation(
        self,
    ) -> None:
        """Concurrent review matrices는 각 typed assignment 안에 있고 workflow는 불변입니다."""
        fixture = self._fixture()
        targets = (ActorId("codex:final-reviewer-a"), ActorId("codex:final-reviewer-b"))
        for target in targets:
            fixture.start_actor(target)
        before = fixture.workflow_snapshot()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = tuple(
                executor.map(
                    lambda target: fixture.begin(
                        target,
                        kind="final-local-review",
                        reviewed_head_sha="f" * 40,
                    ),
                    targets,
                )
            )

        state = fixture.inspect()
        matrices = []
        for result in results:
            delegation = state.delegations[DelegationId(str(result["delegation_id"]))]
            assignment = json.loads(delegation.assignment)
            matrices.append(assignment["review_acceptance_matrix"])
        self.assertEqual(2, len(state.delegations))
        self.assertTrue(all(matrix["row_count"] == 14 for matrix in matrices))
        self.assertEqual(before, fixture.workflow_snapshot())

    def test_submit_is_target_authorized_and_persists_content_addressed_result(self) -> None:
        """Exact target만 immutable artifact를 typed reported result에 결속할 수 있습니다."""
        fixture = self._fixture()
        target_actor_id = ActorId("codex:reviewer")
        wrong_actor_id = ActorId("codex:wrong-reviewer")
        fixture.start_actor(target_actor_id)
        fixture.start_actor(wrong_actor_id)
        begun = fixture.begin(target_actor_id)

        wrong = fixture.run_cli(
            "submit",
            "--delegation-id",
            str(begun["delegation_id"]),
            "--target-agent-id",
            str(target_actor_id),
            "--verdict",
            "pass",
            "--summary",
            "잘못된 reporter입니다.",
            actor_id=wrong_actor_id,
        )
        submitted = fixture.submit(begun, target_actor_id)
        duplicate = fixture.submit(
            begun,
            target_actor_id,
            summary="이미 보고된 result를 교체합니다.",
        )
        result = json.loads(submitted.stdout)
        delegation = fixture.inspect().delegations[DelegationId(str(begun["delegation_id"]))]

        self.assertNotEqual(0, wrong.returncode)
        self.assertEqual(0, submitted.returncode, submitted.stderr)
        self.assertNotEqual(0, duplicate.returncode)
        self.assertEqual(DelegationStatus.REPORTED, delegation.status)
        self.assertEqual(result["outcome_ref"], delegation.result.outcome_ref)
        self.assertTrue(str(result["outcome_ref"]).startswith("sha256:"))
        self.assertEqual(1, len(fixture.artifact_files))

    def test_complete_requires_exact_result_then_consumes_typed_delegation(self) -> None:
        """Owner complete는 target과 outcome ref를 검증한 뒤 reported를 consumed로 바꿉니다."""
        fixture = self._fixture()
        target_actor_id = ActorId("codex:reviewer")
        fixture.start_actor(target_actor_id)
        begun = fixture.begin(target_actor_id)
        submitted = fixture.submit(begun, target_actor_id)
        self.assertEqual(0, submitted.returncode, submitted.stderr)
        result = json.loads(submitted.stdout)

        wrong = fixture.run_cli(
            "complete",
            "--delegation-id",
            str(begun["delegation_id"]),
            "--target-agent-id",
            "codex:someone-else",
            "--outcome-ref",
            str(result["outcome_ref"]),
        )
        completed = fixture.complete(begun, result)
        delegation = fixture.inspect().delegations[DelegationId(str(begun["delegation_id"]))]

        self.assertNotEqual(0, wrong.returncode)
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual(DelegationStatus.CONSUMED, delegation.status)
        completion = json.loads(completed.stdout)
        self.assertEqual("result-applied", completion["outcome"])
        self.assertEqual(fixture.session_id, completion["owner_session_id"])
        self.assertEqual(str(fixture.root_actor_id), completion["owner_actor_id"])

    def test_abort_uses_typed_cancellation_without_fake_review_verification(self) -> None:
        """Owner abort는 pending assignment를 cancel하고 review pass receipt를 꾸미지 않습니다."""
        fixture = self._fixture()
        target_actor_id = ActorId("codex:final-reviewer")
        fixture.start_actor(target_actor_id)
        before = fixture.workflow_snapshot()
        begun = fixture.begin(
            target_actor_id,
            kind="final-local-review",
            reviewed_head_sha="a" * 40,
        )

        aborted = fixture.run_cli(
            "abort",
            "--delegation-id",
            str(begun["delegation_id"]),
            "--target-agent-id",
            str(target_actor_id),
            "--outcome-ref",
            "spawn:error",
        )
        state = fixture.inspect()
        delegation = state.delegations[DelegationId(str(begun["delegation_id"]))]
        completion = json.loads(aborted.stdout)

        self.assertEqual(0, aborted.returncode, aborted.stderr)
        self.assertEqual(DelegationStatus.CANCELLED, delegation.status)
        self.assertEqual("spawn-failed", completion["outcome"])
        self.assertEqual(fixture.session_id, completion["owner_session_id"])
        self.assertEqual(str(fixture.root_actor_id), completion["owner_actor_id"])
        self.assertNotIn("review_verification", completion)
        self.assertEqual(before, fixture.workflow_snapshot())

    def test_final_review_freezes_matrix_inside_canonical_assignment(self) -> None:
        """Frozen review matrix는 별도 completion projection 없이 typed assignment가 소유합니다."""
        fixture = self._fixture()
        target_actor_id = ActorId("codex:final-reviewer")
        fixture.start_actor(target_actor_id)
        before = fixture.workflow_snapshot()

        begun = fixture.begin(
            target_actor_id,
            kind="final-local-review",
            reviewed_head_sha="b" * 40,
        )
        delegation = fixture.inspect().delegations[DelegationId(str(begun["delegation_id"]))]
        assignment = json.loads(delegation.assignment)
        matrix = assignment["review_acceptance_matrix"]

        self.assertEqual(14, matrix["row_count"])
        self.assertEqual("b" * 40, matrix["head_sha"])
        self.assertEqual(64, len(matrix["matrix_id"]))
        self.assertEqual(matrix, begun["review_acceptance_matrix"])
        self.assertEqual(
            DelegationTopologyPolicy.DIRECT_CHILD,
            delegation.topology_policy,
        )
        self.assertEqual(before, fixture.workflow_snapshot())
        self.assertNotIn("delegate_pending", fixture.inspect().to_payload())

    def test_final_review_rejects_incomplete_rows_or_missing_harness_audit(self) -> None:
        """Structured local review는 frozen rows와 세 source audit를 모두 요구합니다."""
        fixture = self._fixture()
        target_actor_id = ActorId("codex:final-reviewer")
        fixture.start_actor(target_actor_id)
        begun = fixture.begin(
            target_actor_id,
            kind="final-local-review",
            reviewed_head_sha="c" * 40,
        )

        incomplete = fixture.submit(
            begun,
            target_actor_id,
            extra_arguments=("--verified-review-row", "C01"),
        )
        no_audit_arguments: list[str] = []
        for row_id in REVIEW_ROW_IDS:
            no_audit_arguments.extend(("--verified-review-row", row_id))
        no_audit = fixture.submit(
            begun,
            target_actor_id,
            extra_arguments=no_audit_arguments,
        )

        self.assertNotEqual(0, incomplete.returncode)
        self.assertIn("every frozen matrix row", incomplete.stderr)
        self.assertNotEqual(0, no_audit.returncode)
        self.assertIn(
            "must audit git diff, process state, and execution trajectory", no_audit.stderr
        )
        delegation = fixture.inspect().delegations[DelegationId(str(begun["delegation_id"]))]
        self.assertEqual(DelegationStatus.PENDING, delegation.status)

    def test_blocking_review_preserves_structured_finding_in_artifact_completion(self) -> None:
        """Block verdict는 frozen row와 reproduction이 있는 finding을 full artifact로 보존합니다."""
        fixture = self._fixture()
        target_actor_id = ActorId("codex:blocking-reviewer")
        fixture.start_actor(target_actor_id)
        begun = fixture.begin(
            target_actor_id,
            kind="final-local-review",
            reviewed_head_sha="e" * 40,
        )
        finding = {
            "stable_key": "C06-MISSING-BRANCH-TEST",
            "row_id": "C06",
            "summary": "신규 분기 테스트가 없습니다.",
            "reproduction_command": "uv run python -m unittest tests.test_branch",
            "expected": "exit=0",
            "actual": "exit=1",
            "impact": "신규 분기의 회귀가 검출되지 않습니다.",
            "root_cause_key": "missing-branch-test",
        }
        arguments: list[str] = []
        for row_id in REVIEW_ROW_IDS:
            arguments.extend(("--verified-review-row", row_id))
        arguments.extend(self._harness_audit_arguments())
        arguments.extend(("--review-finding-json", json.dumps(finding)))

        submitted = fixture.submit(
            begun,
            target_actor_id,
            verdict="block",
            summary="재현 가능한 blocker 한 건입니다.",
            extra_arguments=arguments,
        )
        self.assertEqual(0, submitted.returncode, submitted.stderr)
        result = json.loads(submitted.stdout)
        completed = fixture.complete(begun, result)
        self.assertEqual(0, completed.returncode, completed.stderr)
        completion = json.loads(completed.stdout)
        report = completion["review_report"]
        if not isinstance(report, Mapping):
            raise TypeError("review report fixture must be an object")

        self.assertEqual([finding], report["review_findings"])
        self.assertEqual([finding["summary"]], result["blocking_findings"])
        delegation = fixture.inspect().delegations[DelegationId(str(begun["delegation_id"]))]
        self.assertEqual(DelegationStatus.CONSUMED, delegation.status)

    def test_review_completion_reconstructs_full_artifact_report_without_workflow_mutation(
        self,
    ) -> None:
        """Owner completion은 artifact를 검증하되 workflow payload나 revision을 바꾸지 않습니다."""
        fixture = self._fixture()
        target_actor_id = ActorId("codex:final-reviewer")
        fixture.start_actor(target_actor_id)
        before = fixture.workflow_snapshot()
        begun = fixture.begin(
            target_actor_id,
            kind="final-local-review",
            reviewed_head_sha="d" * 40,
        )
        arguments: list[str] = []
        for row_id in REVIEW_ROW_IDS:
            arguments.extend(("--verified-review-row", row_id))
        arguments.extend(self._harness_audit_arguments())
        note = {
            "stable_key": "C02-REBUTTED-TYPE-RISK",
            "row_id": "C02",
            "summary": "타입 위험 반박을 재검증했습니다.",
            "severity": "resolved",
            "impact": "정규화된 입력만 받습니다.",
            "root_cause_key": "type-risk",
            "disposition": "rebutted",
            "evidence_command": "uv run python -m unittest tests.test_type_contract",
            "expected": "exit=0",
            "actual": "exit=0",
        }
        arguments.extend(("--review-note-json", json.dumps(note)))

        submitted = fixture.submit(
            begun,
            target_actor_id,
            extra_arguments=arguments,
        )
        self.assertEqual(0, submitted.returncode, submitted.stderr)
        result = json.loads(submitted.stdout)
        completed = fixture.complete(begun, result)
        completion = json.loads(completed.stdout)
        review_report = completion["review_report"]
        verification = completion["review_verification"]
        if not isinstance(review_report, Mapping) or not isinstance(verification, Mapping):
            raise TypeError("review receipt fixture must contain objects")

        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual([note], review_report["review_notes"])
        self.assertEqual(14, verification["verified_row_count"])
        self.assertEqual(1, verification["review_note_count"])
        self.assertEqual(str(result["outcome_ref"]), completion["outcome_ref"])
        self.assertEqual(before, fixture.workflow_snapshot())

    def test_delta_inheritance_uses_consumed_assignment_and_digest_verified_artifact(self) -> None:
        """Delta review prior proof는 consumed typed delegation과 exact artifact로 재구성됩니다."""
        fixture = self._fixture()
        first_head, second_head = fixture.create_review_heads()
        first_actor = ActorId("codex:first-reviewer")
        second_actor = ActorId("codex:delta-reviewer")
        fixture.start_actor(first_actor)
        fixture.start_actor(second_actor)
        for assignment in (
            "Inspect the installed package",
            '"generic JSON string"',
            "[]",
            '{"workflow_id":"other-workflow","kind":"final-local-review"}',
            json.dumps({"workflow_id": str(fixture.workflow_id), "kind": "package-check"}),
            json.dumps({"workflow_id": str(fixture.workflow_id), "kind": {"generic": True}}),
        ):
            fixture.consume_generic(first_actor, assignment)
        before = fixture.workflow_snapshot()

        first = fixture.begin(
            first_actor,
            kind="final-local-review",
            reviewed_head_sha=first_head,
        )
        full_arguments: list[str] = []
        for row_id in REVIEW_ROW_IDS:
            full_arguments.extend(("--verified-review-row", row_id))
        full_arguments.extend(self._harness_audit_arguments())
        first_submitted = fixture.submit(
            first,
            first_actor,
            extra_arguments=full_arguments,
        )
        self.assertEqual(0, first_submitted.returncode, first_submitted.stderr)
        first_result = json.loads(first_submitted.stdout)
        first_completed = fixture.complete(first, first_result)
        self.assertEqual(0, first_completed.returncode, first_completed.stderr)
        first_record = fixture.inspect().delegations[DelegationId(str(first["delegation_id"]))]
        self.assertEqual(DelegationStatus.CONSUMED, first_record.status)

        second = fixture.begin(
            second_actor,
            kind="final-local-review",
            reviewed_head_sha=second_head,
        )
        delta_arguments = [
            "--verified-review-row",
            REVIEW_ROW_IDS[0],
            "--inherited-from-head",
            first_head,
        ]
        for row_id in REVIEW_ROW_IDS[1:]:
            delta_arguments.extend(("--inherited-review-row", row_id))
        delta_arguments.extend(self._harness_audit_arguments())
        second_submitted = fixture.submit(
            second,
            second_actor,
            extra_arguments=delta_arguments,
        )
        self.assertEqual(0, second_submitted.returncode, second_submitted.stderr)
        second_result = json.loads(second_submitted.stdout)
        second_completed = fixture.complete(second, second_result)
        self.assertEqual(0, second_completed.returncode, second_completed.stderr)
        completion = json.loads(second_completed.stdout)
        report = completion["review_report"]

        self.assertEqual([REVIEW_ROW_IDS[0]], report["reverified_review_rows"])
        self.assertEqual(list(REVIEW_ROW_IDS[1:]), report["inherited_review_rows"])
        self.assertEqual(first_head, report["inherited_from_head"])
        self.assertEqual(before, fixture.workflow_snapshot())

    def test_full_review_does_not_depend_on_unused_prior_review_proof(self) -> None:
        """새 전수 리뷰는 사용하지 않는 과거 결과의 내용이나 artifact를 신뢰하지 않습니다."""
        fixture = self._fixture()
        _, head = fixture.create_review_heads()
        actor = ActorId("codex:full-reviewer")
        fixture.start_actor(actor)
        generic = fixture.consume_generic(actor, "Review the package independently")
        malformed_review = fixture.consume_generic(actor, json.dumps({
            "workflow_id": str(fixture.workflow_id), "kind": "final-local-review",
        }))
        begun = fixture.begin(actor, kind="final-local-review", reviewed_head_sha=head)
        arguments = list(self._harness_audit_arguments())
        for row in REVIEW_ROW_IDS:
            arguments.extend(("--verified-review-row", row))
        submitted = fixture.submit(begun, actor, extra_arguments=arguments)
        self.assertEqual(0, submitted.returncode, submitted.stderr)
        completed = fixture.complete(begun, json.loads(submitted.stdout))
        self.assertEqual(0, completed.returncode, completed.stderr)
        state = fixture.inspect()
        self.assertEqual("Review the package independently", state.delegations[generic].assignment)
        self.assertEqual(DelegationStatus.CONSUMED, state.delegations[malformed_review].status)

    def test_inheritance_rejects_identified_review_with_invalid_metadata_or_artifact(self) -> None:
        """같은 workflow의 review로 식별한 과거 근거는 strict 검증을 통과해야 합니다."""
        for defect in ("metadata", "artifact"):
            with self.subTest(defect=defect):
                fixture = self._fixture()
                first_head, second_head = fixture.create_review_heads()
                actor = ActorId("codex:delta-reviewer")
                fixture.start_actor(actor)
                prior = fixture.begin(actor, kind="final-local-review", reviewed_head_sha=first_head)
                assignment = fixture.inspect().delegations[DelegationId(prior["delegation_id"])].assignment
                if defect == "metadata":
                    assignment = json.dumps({
                        "workflow_id": str(fixture.workflow_id), "kind": "final-local-review",
                    })
                fixture.consume_generic(actor, assignment)
                current = fixture.begin(actor, kind="final-local-review", reviewed_head_sha=second_head)
                arguments = ["--verified-review-row", "C01", "--inherited-from-head", first_head]
                for row in REVIEW_ROW_IDS[1:]:
                    arguments.extend(("--inherited-review-row", row))
                arguments.extend(self._harness_audit_arguments())
                submitted = fixture.submit(current, actor, extra_arguments=arguments)
                self.assertEqual(2, submitted.returncode, submitted.stderr)
                self.assertIn("identity is incomplete" if defect == "metadata" else "artifact", submitted.stderr)
                self.assertEqual((), fixture.artifact_files)
                record = fixture.inspect().delegations[DelegationId(current["delegation_id"])]
                self.assertEqual(DelegationStatus.PENDING, record.status)

    def test_cross_session_cli_cannot_read_or_mutate_original_workflow(self) -> None:
        """다른 runtime session identity는 원래 workflow나 delegation으로 fallback하지 않습니다."""
        fixture = self._fixture()
        target_actor_id = ActorId("codex:reviewer")
        fixture.start_actor(target_actor_id)

        result = fixture.run_cli(
            "begin",
            "--kind",
            "pr-review",
            "--target",
            "reviewer",
            "--scope",
            "review",
            "--target-agent-id",
            str(target_actor_id),
            session_id="other-session",
        )

        self.assertNotEqual(0, result.returncode)
        self.assertEqual({}, fixture.inspect().delegations)
        self.assertFalse(fixture.legacy_state_path.exists())

    def test_inheritance_is_independent_of_conflicting_prior_record_order(self) -> None:
        """동일 head의 상충하는 결과는 ID 순서와 무관하게 차단하고 일치하는 pass는 허용합니다."""
        for verdicts in (("pass", "block"), ("block", "pass"), ("pass", "pass")):
            with self.subTest(verdicts=verdicts):
                fixture = self._fixture()
                first_head, second_head = fixture.create_review_heads()
                actor = ActorId("codex:reviewer")
                fixture.start_actor(actor)
                claims = sorted(
                    [fixture.begin(actor, kind="final-local-review", reviewed_head_sha=first_head)
                     for _ in range(2)],
                    key=lambda claim: claim["delegation_id"],
                )
                for claim, verdict in zip(claims, verdicts, strict=True):
                    arguments = list(self._harness_audit_arguments())
                    for row in REVIEW_ROW_IDS:
                        arguments.extend(("--verified-review-row", row))
                    if verdict == "block":
                        arguments.extend(("--review-finding-json", json.dumps({
                            "stable_key": "C09-PRIOR-CONFLICT",
                            "row_id": "C09",
                            "summary": "Prior review reported a persistent defect.",
                            "reproduction_command": "python -m unittest prior_failure",
                            "expected": "pass", "actual": "failed",
                            "impact": "The prior head is not accepted.",
                            "root_cause_key": "prior-conflict",
                        })))
                    submitted = fixture.submit(claim, actor, verdict=verdict, extra_arguments=arguments)
                    self.assertEqual(0, submitted.returncode, submitted.stderr)
                    completed = fixture.complete(claim, json.loads(submitted.stdout))
                    self.assertEqual(0, completed.returncode, completed.stderr)
                current = fixture.begin(actor, kind="final-local-review", reviewed_head_sha=second_head)
                arguments = ["--verified-review-row", "C01", "--inherited-from-head", first_head]
                for row in REVIEW_ROW_IDS[1:]:
                    arguments.extend(("--inherited-review-row", row))
                arguments.extend(self._harness_audit_arguments())
                submitted = fixture.submit(current, actor, extra_arguments=arguments)
                expected = 0 if verdicts == ("pass", "pass") else 2
                self.assertEqual(expected, submitted.returncode, submitted.stderr)
                if expected:
                    self.assertIn("conflicting prior review", submitted.stderr)
                    record = fixture.inspect().delegations[DelegationId(current["delegation_id"])]
                    self.assertEqual(DelegationStatus.PENDING, record.status)

    def _harness_audit_arguments(self) -> tuple[str, ...]:
        """세 source의 typed SHA-256 audit locator를 반환합니다."""
        return (
            "--harness-audit-evidence",
            f"git_diff:sha256:{'a' * 64}",
            "--harness-audit-evidence",
            f"process_state:sha256:{'b' * 64}",
            "--harness-audit-evidence",
            f"execution_trajectory:sha256:{'c' * 64}",
        )

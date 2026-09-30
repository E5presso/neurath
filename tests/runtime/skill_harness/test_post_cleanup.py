"""Real cleanup and authenticated adaptive completion through the surviving issuer."""
import hashlib
import json
import subprocess
from unittest import TestCase, mock

from scripts.agent_harness.tests import test_adaptive_control_authority as authority_tests
from scripts.agent_harness.session_kernel import (
    ForegroundTurnPrompted, SessionLocator,
)
from scripts.agent_harness.skill_state_store import SkillStateStore
from scripts.agent_harness.task_service import TaskService
from scripts.agent_harness.worktree_registry import (
    WorktreeIdentityResolver, WorktreeRegistry, WorktreeClaim,
)
from scripts.skill_harness.phase_runner import PhaseRunState, SkillContractRepository
from neurath.resources import BUNDLE
from neurath.runtime.bundled_services import service
from neurath.runtime.post_cleanup import inspect_cleaned_worker, finalize_cleaned_worker
from neurath.providers.job_store import open_store
from neurath.providers.job_recovery import JobRecovery


class PostCleanupTest(TestCase):
    def test_finalization_preserves_owner_records_issuer_and_is_atomic_and_idempotent(self):
        original = authority_tests.WorkflowStarted
        contract = SkillContractRepository(BUNDLE).get("process-ticket")
        phase = PhaseRunState.initialize(contract, "distinct-workflow-run", authority_tests.AdaptiveAuthorityFixture._GOAL)
        for entry in contract.phases[:-1]:
            phase = phase.with_completed_phase(contract, entry.id, "completed",
                ("agent_session_context: route_owner=autopilot terminal_sink=autopilot merge_policy=auto",),
                "Fixture prerequisite completed", None)
        def start(**kwargs):
            return original(**{**kwargs, "kind": "process-ticket",
                "payload": {**kwargs["payload"], "phase_run": phase.as_payload()}})
        with mock.patch.object(authority_tests, "WorkflowStarted", side_effect=start):
            fixture = authority_tests.AdaptiveAuthorityFixture().__enter__()
        self.addCleanup(fixture.__exit__, None, None, None)
        root = fixture.repository.resolve()
        def git(*args):
            return subprocess.run(["git", "-C", str(root), *args], check=True,
                                  capture_output=True, text=True).stdout.strip()
        ignore = root / ".gitignore"
        ignore.write_text(ignore.read_text() + ".neurath/local/\n.agents/resources/\n.tasks/\n")
        contracts = root / ".agents/skills/contracts.json"
        contracts.parent.mkdir(parents=True, exist_ok=True)
        contracts.write_bytes((BUNDLE / ".agents/skills/contracts.json").read_bytes())
        git("add", ".gitignore", ".agents/skills/contracts.json")
        git("commit", "-qm", "terminal fixture")
        branch = git("branch", "--show-current")
        remote = root.parent / (root.name + "-remote.git")
        self.addCleanup(__import__('shutil').rmtree, remote, True)
        subprocess.run(["git", "clone", "--bare", str(root), str(remote)], check=True, capture_output=True)
        git("remote", "add", "origin", str(remote)); git("fetch", "origin")
        worktree = root / ".tasks/worker"
        git("worktree", "add", "-b", "task/generic", str(worktree))
        owner = fixture.owner
        owner.apply(ForegroundTurnPrompted(session_id=owner.session_id, actor_id=owner.actor_id,
            vendor_turn_id="assignment-turn", prompt_digest=hashlib.sha256(b"finish the ticket").hexdigest(),
            idempotency_key="fixture-prompt"))
        tasks = TaskService(owner)
        defined = tasks.define([{"key": "finish", "title": "Finish merged cleanup",
            "goal": fixture._GOAL, "sources": [], "acceptance": ["final workflow and cleanup"],
            "dependencies": []}], expected_revision=0, key="define")
        task_id = defined["tasks"][0]["id"]
        tasks.start(task_id, expected_revision=1, expected_task_revision=1, key="start")
        head = git("rev-parse", "HEAD")
        (worktree / "worker-ticket.txt").write_text("ticket branch differs from primary\n")
        subprocess.run(["git", "-C", str(worktree), "add", "worker-ticket.txt"], check=True)
        subprocess.run(["git", "-C", str(worktree), "-c", "user.name=Neurath Test",
                        "-c", "user.email=test@example.invalid", "commit", "-qm",
                        "advance ticket branch"], check=True)
        ticket_head = subprocess.run(["git", "-C", str(worktree), "rev-parse", "HEAD"],
                                     check=True, capture_output=True, text=True).stdout.strip()
        self.assertNotEqual(head, ticket_head)
        SkillStateStore(owner, fixture.workflow_id).update({
            "merged": {"state": "MERGED", "pr_number": 1, "merge_commit_oid": head},
            "monitor_event_ack": {"reason": "merged", "event_id": "actual-ack",
                "evidence": ["terminal_readback:headRefOid=" + ticket_head]}})
        # Use an actual executable claim. A semantic-only completion does not
        # exercise the historical source fingerprint after the worker is gone.
        contract = fixture._contract(authority_tests.EvidenceKind.PROPERTY_TEST,
                                     authority_tests.OracleOwner.EXECUTABLE)
        executable = fixture.execute_evidence()
        executable_claim, coverage_claim = fixture.mixed_claims(executable)
        evaluator_result = fixture.write_artifact("cleanup-executable",
            (executable_claim, coverage_claim),
            report_overrides={"goal_fingerprint": coverage_claim["goal_fingerprint"]},
            contract=contract)
        lineage = fixture.independent_lineage("cleanup-executable", evaluator_result)
        candidate = fixture.mixed_snapshot(lineage, executable)
        assignment, candidate_ref = fixture.prepare_candidate(candidate.state)
        fixture.transition_delegation("cleanup-executable", evaluator_result,
            lifecycle="consumed",
            assignment_overrides={"goal_fingerprint": coverage_claim["goal_fingerprint"]},
            candidate_state=candidate.state,
            prepared_assignment=assignment,
            prepared_candidate_ref=candidate_ref)
        fixture.persist_snapshot(candidate)
        identity = WorktreeIdentityResolver().resolve(worktree)
        WorktreeRegistry(SessionLocator.from_worktree(root)).claim(WorktreeClaim(
            worktree_id=identity.worktree_id, path=identity.path,
            session_id=owner.session_id, actor_id=owner.actor_id))
        cleanup = service("cleanup").MergeCleanupApplication().run_bound(handle=owner, cwd=worktree,
            workflow_id=fixture.workflow_id, base_branch=branch, remote_ref="origin/" + branch)
        self.assertFalse(worktree.exists())
        store = open_store(root)
        created = {"provider": "codex", "native_session": str(owner.session_id),
                   "transport": "codex-app-server", "worktree": str(worktree)}
        result = {"created": created, "worker_generation": 1, "closure": {
            "native_session": str(owner.session_id), "transport": "codex-app-server",
            "native_process_exited": True, "connection_closed": True}}
        with store.connection() as db:
            db.execute("INSERT INTO provider_jobs VALUES (?,?,?,?,?,?,0,0)",
                ("provider-run", "codex:issuer", json.dumps({"provider": "codex", "worktree": str(worktree)}),
                 "accepted", None, str(root)))
        lease = JobRecovery(store).claim_worker("codex:issuer", "provider-run")
        lease.close()
        with store.connection() as db:
            db.execute("UPDATE provider_jobs SET status='completed',result=? WHERE id='provider-run'",
                       (json.dumps(result),))
        observed = inspect_cleaned_worker(root, "codex:issuer", "provider-run", str(fixture.workflow_id))
        evidence = ["merge_command: external issuer completed gh pr merge --delete-branch",
            "merge_approval: auto_merge_invocation=true", "github_merge_readback: state=MERGED",
            "issue_status_readback: issue_status=Done", "parent_issue_completion_readback: parent_issue=none",
            "branch_cleanup_readback: remote_branch_deleted=true local_branch_removed=true",
            "worktree_cleanup_readback: worktree_removed=true", "terminal_report: status=merged",
            "gap_dispatch_check: gaps_detected=none gaps_dispatched=none"]
        fields = {"run_id": "provider-run", "workflow_id": str(fixture.workflow_id),
            "expected_revision": observed["workflow_revision"], "expected_list_revision": 2,
            "expected_task_revision": 2, "task_id": task_id, "evidence": evidence,
            "summary": "Recovered completed cleanup", "key": "finish"}
        from scripts.agent_harness.state_handle import StateHandle, RuntimeEnvironmentResolver
        issuer = StateHandle.initialize(SessionLocator.from_worktree(root),
            RuntimeEnvironmentResolver().resolve({"CODEX_THREAD_ID": "issuer"}))
        for changed, message in (({"expected_revision": 0}, "revision"),
                ({"task_id": "foreign-task"}, "task")):
            with self.subTest(changed=changed), self.assertRaisesRegex(ValueError, message):
                finalize_cleaned_worker(root, issuer, "codex:issuer", {**fields, **changed})
        with self.assertRaisesRegex(ValueError, "owner"):
            inspect_cleaned_worker(root, "codex:foreign", "provider-run", str(fixture.workflow_id))
        from scripts.agent_harness.runtime_database import RuntimeDatabase
        class Rollback(Exception):
            pass
        # Corrupt fixture authorities inside rolled-back transactions; no negative
        # case may change the source phase or resolve the task.
        for field, value in (("owner", "codex:foreign"), ("source", "another-session"),
                             ("closure", False), ("generation", 2)):
            with self.subTest(authority=field), self.assertRaises(Rollback):
                with RuntimeDatabase(root).transaction() as tx:
                    changed_result = json.loads(json.dumps(result))
                    if field == "owner":
                        tx.connection.execute("UPDATE provider_jobs SET owner='codex:foreign' WHERE id='provider-run'")
                    elif field == "generation":
                        tx.connection.execute("UPDATE provider_worker_leases SET generation=2 WHERE run_id='provider-run'")
                    else:
                        if field == "source":
                            changed_result["created"]["native_session"] = value
                        else:
                            changed_result["closure"]["connection_closed"] = value
                        tx.connection.execute("UPDATE provider_jobs SET result=? WHERE id='provider-run'",
                                              (json.dumps(changed_result),))
                    with self.assertRaises(ValueError):
                        finalize_cleaned_worker(root, issuer, "codex:issuer", fields)
                    raise Rollback()
        with self.assertRaises(Rollback):
            with RuntimeDatabase(root).transaction():
                SkillStateStore(owner, fixture.workflow_id).update({"merge_cleanup_receipt": {
                    **cleanup, "cleanup_reservation_fencing_token_sha256": "0" * 64}})
                with self.assertRaisesRegex(ValueError, "fencing"):
                    finalize_cleaned_worker(root, issuer, "codex:issuer", fields)
                raise Rollback()
        with self.assertRaises(Rollback):
            with RuntimeDatabase(root).transaction():
                tasks.resolve(task_id, expected_revision=2, expected_task_revision=2, key="original-done",
                    status="succeeded", references=["fixture:original"], summary="Original requirement done")
                pending = tasks.define([{"key": "unrelated", "title": "Unrelated work",
                    "goal": "Migrate an unrelated database", "sources": [], "acceptance": ["database moved"],
                    "dependencies": []}], expected_revision=3, key="other-task")
                unrelated_id = pending["tasks"][-1]["id"]
                tasks.start(unrelated_id, expected_revision=4, expected_task_revision=1, key="other-start")
                with self.assertRaisesRegex(ValueError, "independent workflow association"):
                    finalize_cleaned_worker(root, issuer, "codex:issuer", {**fields,
                        "task_id": unrelated_id, "expected_list_revision": 5})
                raise Rollback()
        # A legacy follow-up task needs exact independent semantic association,
        # not merely a shared prompt or the original issuer's prose.
        with self.assertRaises(Rollback):
            with RuntimeDatabase(root).transaction():
                tasks.resolve(task_id, expected_revision=2, expected_task_revision=2, key="original-done",
                    status="succeeded", references=["fixture:original"], summary="Original requirement done")
                legacy = tasks.define([{"key": "legacy-final", "title": "Record final cleanup",
                    "goal": "Record the terminal workflow and cleanup outcome", "sources": [],
                    "acceptance": ["Last phase, workflow and task are terminal"], "dependencies": []}],
                    expected_revision=3, key="legacy-task")
                legacy_id = legacy["tasks"][-1]["id"]
                tasks.start(legacy_id, expected_revision=4, expected_task_revision=1, key="legacy-start")
                scope = inspect_cleaned_worker(root, "codex:issuer", "provider-run",
                                              str(fixture.workflow_id))["task_scopes"][0]
                delegation = self._attest_scope(issuer, scope)
                recovered = finalize_cleaned_worker(root, issuer, "codex:issuer", {**fields,
                    "task_id": legacy_id, "expected_list_revision": 5,
                    "task_scope_delegation_id": str(delegation)})
                self.assertEqual("finalized", recovered["status"])
                self.assertTrue(tasks.list()["all_succeeded"])
                raise Rollback()
        fields["task_scope_delegation_id"] = str(self._attest_scope(issuer,
            inspect_cleaned_worker(root, "codex:issuer", "provider-run", str(fixture.workflow_id))["task_scopes"][0]))
        # An invalid task CAS rolls back the phase and kernel event as well.
        with self.assertRaises(ValueError):
            finalize_cleaned_worker(root, issuer, "codex:issuer", {**fields, "expected_list_revision": 1})
        self.assertEqual(observed["workflow_revision"], owner.inspect().workflows[fixture.workflow_id].revision)
        # The surviving primary advances after cleanup; the original worker's
        # executable receipt must remain tied to its recorded bytes, not replay
        # against this newer checkout.
        (root / "post-cleanup-new-source.txt").write_text("new primary source\n")
        git("add", "post-cleanup-new-source.txt")
        git("commit", "-qm", "advance surviving primary")
        completed = finalize_cleaned_worker(root, issuer, "codex:issuer", fields)
        self.assertEqual("completed", completed["workflow_status"])
        self.assertEqual("codex:issuer", completed["issuer"])
        self.assertEqual(str(owner.actor_id), completed["original_owner"])
        self.assertFalse(completed["cleanup_repeated"])
        self.assertEqual(completed, finalize_cleaned_worker(root, issuer, "codex:issuer", fields))
        self.assertTrue(tasks.list()["all_succeeded"])
        self.assertEqual(cleanup, owner.inspect().workflows[fixture.workflow_id].payload["skill_state"]["merge_cleanup_receipt"])
        self.assertFalse(worktree.exists())

    def _attest_scope(self, issuer, scope):
        from scripts.agent_harness.session_kernel import (
            ActorId, ActorKind, ActorLineageAssurance, ActorStarted,
            DelegationAssigned, DelegationConsumed, DelegationId, DelegationReported,
            DelegationResult, DelegationTopologyPolicy,
        )
        from scripts.agent_harness.artifact_store import SessionArtifactStore
        child = ActorId("codex:scope-reviewer")
        issuer.apply(ActorStarted(session_id=issuer.session_id, actor_id=child,
            parent_actor_id=issuer.actor_id, kind=ActorKind.SUBAGENT,
            lineage_assurance=ActorLineageAssurance.HOST_ATTESTED, idempotency_key="scope-child"))
        delegation = DelegationId("scope-review")
        issuer.apply(DelegationAssigned(session_id=issuer.session_id, delegation_id=delegation,
            owner_actor_id=issuer.actor_id, target_actor_id=child,
            assignment=json.dumps({"kind": "post-cleanup-task-scope", "scope": scope}),
            topology_policy=DelegationTopologyPolicy.DIRECT_CHILD, idempotency_key="scope-assign"))
        from scripts.agent_harness.state_handle import StateHandle, RuntimeIdentityBinding
        child_handle = StateHandle(issuer._kernel, RuntimeIdentityBinding(
            runtime=issuer.inspect().session.runtime, session_id=issuer.session_id,
            root_actor_id=issuer.actor_id, actor_id=child))
        artifact = SessionArtifactStore(child_handle).put_json({
            "schema": "neurath.post-cleanup-task-scope.v1", "scope": scope,
            "task_matches_terminal_workflow": True,
            "reason": "Fixture reviewer verified that every task criterion is terminal bookkeeping."})
        child_handle.apply(DelegationReported(session_id=issuer.session_id, delegation_id=delegation,
            reporter_actor_id=child, result=DelegationResult(verdict="pass", summary="scope verified",
                outcome_ref=artifact.reference, blocking_findings=()), idempotency_key="scope-report"))
        issuer.apply(DelegationConsumed(session_id=issuer.session_id, delegation_id=delegation,
            consumer_actor_id=issuer.actor_id, idempotency_key="scope-consume"))
        return delegation

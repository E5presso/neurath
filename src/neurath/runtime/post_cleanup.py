"""Issuer-authorized terminal bookkeeping after an owned worker checkout is gone.

No native identity is rebound, no worker is resumed, and no Git mutation is run.
The source facade is private and permits only the last process-ticket transitions.
The actual issuer is retained in the atomic recovery and task-result receipts.
"""
import hashlib
import json
import os
from pathlib import Path

from neurath.serialization import canonical


def _source(root, issuer, run_id, workflow_id, *, transaction=None):
    from neurath.providers.job_store import open_store, owned_job
    from scripts.agent_harness.session_kernel import SessionKernel, SessionLocator, SessionId
    from scripts.agent_harness.worktree_registry import WorktreeRegistry, WorktreeId
    from neurath.runtime.process_tasks import _git
    root = Path(root).resolve()
    locator = SessionLocator.from_worktree(root)
    if root != locator.control_root.resolve():
        raise ValueError("post-cleanup recovery requires the surviving primary checkout")
    with open_store(root).connection() as db:
        job = dict(owned_job(db, issuer, run_id))
    request, result = json.loads(job["request"]), json.loads(job["result"] or "{}")
    created, closure = result.get("created", {}), result.get("closure", {})
    provider = request.get("provider", "codex")
    transport = {"codex": "codex-app-server", "claude-code": "claude-agent-sdk"}.get(provider)
    if (job["cancel_requested"] or job["status"] not in {"completed", "failed"}
            or not transport or created.get("provider") != provider
            or created.get("transport") != transport or closure.get("transport") != transport
            or not created.get("native_session")
            or created.get("native_session") != closure.get("native_session")
            or closure.get("connection_closed") is not True
            or closure.get("native_process_exited") is not True
            or created.get("worktree") != request.get("worktree")
            or type(result.get("worker_generation")) is not int):
        raise ValueError("original owned worker closure or source session is unverified")
    kernel = SessionKernel(locator)
    source = kernel.inspect(SessionId(created["native_session"]))
    workflow = source.workflows.get(workflow_id)
    owner = f"{provider}:session:{created['native_session']}"
    if (str(source.session.root_actor_id) != owner or workflow is None
            or str(workflow.owner_actor_id) != owner or workflow.kind != "process-ticket"):
        raise ValueError("cleanup workflow has a different original owner")
    cleanup = workflow.payload.get("skill_state", {}).get("merge_cleanup_receipt")
    if not isinstance(cleanup, dict):
        raise ValueError("source workflow has no completed cleanup receipt")
    registry = WorktreeRegistry(locator)
    release = (registry.release_receipt(WorktreeId(cleanup["worktree_id"])) if transaction is None
               else registry.release_receipt_transaction(transaction, WorktreeId(cleanup["worktree_id"])))
    if not release or release["kind"] != "cleanup":
        raise ValueError("cleanup release was replaced or is missing")
    claim = release["claim"]
    if (cleanup.get("schema_version") != 3
            or any(cleanup.get(key) is not True for key in (
                "worktree_removed", "branch_removed", "worktree_claim_released"))
            or cleanup.get("owner_session_id") != str(source.session.id)
            or cleanup.get("owner_actor_id") != owner
            or claim["session_id"] != str(source.session.id) or claim["actor_id"] != owner
            or claim["status"] != "cleanup-reserved"
            or claim["worktree_id"] != cleanup["worktree_id"]
            or claim["path"] != cleanup.get("worktree")
            or claim["path"] != created["worktree"]
            or claim["lease_epoch"] != cleanup.get("released_lease_epoch")
            or hashlib.sha256(claim["fencing_token"].encode()).hexdigest()
                != cleanup.get("cleanup_reservation_fencing_token_sha256")):
        raise ValueError("cleanup receipt differs from the exact original owner and fencing token")
    if os.path.lexists(created["worktree"]):
        raise ValueError("cleaned worker path has been recreated")
    registered = _git(root, "worktree", "list", "--porcelain")
    if "worktree " + created["worktree"] in registered.splitlines():
        raise ValueError("cleaned worker is still registered")
    if _git(root, "for-each-ref", "--format=%(refname)", "refs/heads/" + cleanup["branch"]):
        raise ValueError("cleaned worker branch has been recreated")
    if (_git(root, "branch", "--show-current") != cleanup["base_branch"]
            or _git(root, "rev-parse", "--is-bare-repository") != "false"):
        raise ValueError("surviving primary checkout differs from cleanup")
    # The primary may advance after cleanup; the recorded result must remain in its history.
    import subprocess
    if subprocess.run(["git", "-C", str(root), "merge-base", "--is-ancestor",
                       cleanup["root_head"], "HEAD"], capture_output=True, check=False).returncode:
        raise ValueError("cleanup root commit is no longer in primary history")
    return kernel, source, workflow, cleanup, release, result


def inspect_cleaned_worker(root, issuer, run_id, workflow_id):
    """Read only the exact source derived from this issuer's persisted provider run."""
    from scripts.agent_harness.runtime_database import RuntimeDatabase
    from scripts.agent_harness.task_service import read_ledger
    _, source, workflow, cleanup, release, result = _source(root, issuer, run_id, workflow_id)
    with RuntimeDatabase(Path(root)).transaction() as tx:
        _, ledger = read_ledger(tx, source)
    return {"source_session": str(source.session.id), "original_owner": str(workflow.owner_actor_id),
            "issuer": issuer, "run_id": run_id, "worker_generation": result["worker_generation"],
            "workflow_id": workflow_id, "workflow_revision": workflow.revision,
            "workflow_status": workflow.status.value, "phase": workflow.payload.get("phase_run"),
            "cleanup": cleanup, "release_reference": release["reference"],
            "task_list_revision": ledger.revision,
            "tasks": [{"id": t.id, "revision": t.revision, "status": t.status.value,
                       "goal": t.definition.goal, "acceptance": list(t.definition.acceptance)}
                      for t in ledger.tasks],
            "task_scopes": [_task_scope(issuer, run_id, source, workflow, release, ledger, task)
                            for task in ledger.tasks if not task.status.terminal]}


def _task_scope(issuer, run_id, source, workflow, release, ledger, task):
    return {"issuer": issuer, "run_id": run_id, "source_session": str(source.session.id),
            "original_owner": str(workflow.owner_actor_id), "workflow_id": str(workflow.id),
            "workflow_revision": workflow.revision, "workflow_goal": workflow.goal,
            "release_reference": release["reference"], "task_list_revision": ledger.revision,
            "task_id": task.id, "task_revision": task.revision,
            "definition_digest": task.definition.digest, "task_goal": task.definition.goal,
            "acceptance": list(task.definition.acceptance)}


def _verify_task_scope(issuer_handle, caller, scope, delegation_id):
    """Legacy semantic association requires a genuine independent issuer child report."""
    from scripts.agent_harness.artifact_store import SessionArtifactStore
    from scripts.agent_harness.session_kernel import DelegationStatus, DelegationTopologyPolicy
    delegation = caller.delegations.get(delegation_id)
    if (delegation is None or delegation.owner_actor_id != issuer_handle.actor_id
            or delegation.status is not DelegationStatus.CONSUMED
            or delegation.topology_policy is not DelegationTopologyPolicy.DIRECT_CHILD
            or delegation.result is None or delegation.result.verdict != "pass"
            or delegation.result.blocking_findings
            or json.loads(delegation.assignment) != {"kind": "post-cleanup-task-scope", "scope": scope}):
        raise ValueError("task requires an exact consumed independent workflow association")
    report = SessionArtifactStore(issuer_handle).read_json(delegation.result.outcome_ref)
    if (report.get("schema") != "neurath.post-cleanup-task-scope.v1"
            or report.get("scope") != scope or report.get("task_matches_terminal_workflow") is not True
            or not isinstance(report.get("reason"), str) or not report["reason"].strip()):
        raise ValueError("independent task association report differs from the exact source")


class _TerminalSource:
    """Application-scoped source access, never a native binding or general actor handle."""

    def __init__(self, kernel, source, workflow_id, cleanup_receipt=None):
        self._kernel = kernel
        self.session_id = source.session.id
        self.actor_id = source.session.root_actor_id
        self.workflow_id = workflow_id
        self.post_cleanup_receipt = cleanup_receipt
        self._staged = source

    def _repository_control_root(self):
        return self._kernel._locator.control_root

    def _session_artifact_directory(self):
        return self._kernel._session_paths(self.session_id).artifacts

    def inspect(self):
        return self._staged

    def apply(self, event, expected_revision=None):
        from scripts.agent_harness.session_kernel import WorkflowAdvanced, WorkflowFinalized
        if (type(event) not in {WorkflowAdvanced, WorkflowFinalized}
                or event.session_id != self.session_id or event.actor_id != self.actor_id
                or event.workflow_id != self.workflow_id):
            raise ValueError("post-cleanup capability only permits the exact terminal workflow")
        state = self.inspect()
        old = state.workflows[self.workflow_id].payload
        if ({k: v for k, v in old.items() if k != "phase_run"}
                != {k: v for k, v in event.payload.items() if k != "phase_run"}):
            raise ValueError("post-cleanup capability cannot change source authority")
        # Existing phase validators operate on proposals only. These source-owner
        # events are never issued to the kernel or persisted as native actions.
        from scripts.agent_harness.session_reducer import SessionStateReducer
        self._staged = SessionStateReducer().reduce(state, event).with_revision(state.revision + 1)
        return self._staged


def finalize_cleaned_worker(root, issuer_handle, issuer, fields):
    """Commit final phase, workflow, one task result and issuer audit atomically.

    Evidence remains an explicit issuer report and passes the existing phase runner.
    Cleanup and adaptive authority are independently revalidated; no receipt is forged.
    """
    from neurath.providers.job_store import open_store
    from neurath.providers.job_recovery import JobRecovery
    from scripts.agent_harness.runtime_database import RuntimeDatabase
    from scripts.agent_harness.session_kernel import SessionLocator, WorkflowId
    from scripts.agent_harness.worktree_registry import WorktreeRegistry, WorktreeId
    from scripts.agent_harness.task_service import read_ledger, validate_instruction_sources
    from scripts.agent_harness.task_ledger import TaskStatus, TaskEvidence
    from scripts.agent_harness.artifact_store import SessionArtifactStore
    from scripts.agent_harness.adaptive_control_authority import AdaptiveControlAuthorityVerifier
    from scripts.skill_harness.phase_runner import PhaseRunner, SkillContractRepository
    from scripts.skill_harness.session_phase_store import SessionPhaseRunnerStore

    root = Path(root).resolve()
    run_id, workflow_id = fields["run_id"], fields["workflow_id"]
    observed = inspect_cleaned_worker(root, issuer, run_id, workflow_id)
    registry = WorktreeRegistry(SessionLocator.from_worktree(root))
    recovery = JobRecovery(open_store(root))
    # Lifetime flock prevents a concurrently restored native worker from writing.
    fd = recovery._lock(run_id)
    try:
        with registry.terminal_admission(WorktreeId(observed["cleanup"]["worktree_id"])):
            with RuntimeDatabase(root).transaction() as tx:
                caller = issuer_handle.inspect()  # Live caller guard inside the commit transaction.
                if (caller.session.root_actor_id != issuer_handle.actor_id
                        or issuer != f"{caller.session.runtime.value}:{caller.session.id}"):
                    raise ValueError("post-cleanup requires the actual native issuer root")
                kernel, source, workflow, cleanup, release, result = _source(
                    root, issuer, run_id, workflow_id, transaction=tx)
                lease = tx.connection.execute(
                    "SELECT generation,state FROM provider_worker_leases WHERE run_id=?", (run_id,)).fetchone()
                if (lease is None or lease["generation"] != result["worker_generation"]
                        or lease["state"] == "accepted"):
                    raise ValueError("original worker generation fence changed")
                namespace = "post-cleanup:" + issuer
                request = canonical(fields)
                previous = tx.get(namespace, fields["key"])
                if previous is not None:
                    recorded = json.loads(previous.payload)
                    if recorded["request"] != request:
                        raise ValueError("post-cleanup key reused with different input")
                    return recorded["result"]
                if tx.get("session-migration", str(source.session.id)) is not None:
                    raise ValueError("source ownership was migrated")
                if workflow.revision != fields["expected_revision"]:
                    raise ValueError("source workflow revision changed")
                handle = _TerminalSource(kernel, source, WorkflowId(workflow_id), cleanup)
                store = SessionPhaseRunnerStore.open_existing(handle, WorkflowId(workflow_id))
                phase = store.read()
                if (phase.skill != "process-ticket"
                        or not phase.adaptive_control_required or phase.terminal_state is not None
                        or phase.current_phase_id != phase.phases[-1].id
                        or phase.phases[-1].name != "merge_cleanup"
                        or any(p.status != "completed" for p in phase.phases[:-1])):
                    raise ValueError("source is not awaiting its final merged cleanup phase")
                skill = workflow.payload.get("skill_state", {})
                merged, ack = skill.get("merged", {}), skill.get("monitor_event_ack", {})
                if (merged.get("state") != "MERGED" or ack.get("reason") != "merged"
                        or not ack.get("event_id")
                        or "terminal_readback:headRefOid=" + cleanup["ticket_head_oid"]
                            not in ack.get("evidence", [])):
                    raise ValueError("source lacks exact merged monitor acknowledgement")
                authority = AdaptiveControlAuthorityVerifier(handle, WorkflowId(workflow_id))
                proof = authority.verify_completion(workflow.revision, post_cleanup_receipt=cleanup)
                record, ledger = read_ledger(tx, source)
                task = next((t for t in ledger.tasks if t.id == fields["task_id"]), None)
                if task is None or task.status is not TaskStatus.IN_PROGRESS:
                    raise ValueError("source finalization task is not in progress")
                unfinished = [t for t in ledger.tasks if not t.status.terminal]
                origins = [t for t in ledger.tasks if t.definition.goal == workflow.goal]
                if (unfinished != [task] or not origins
                        or not any(set(task.definition.sources) == set(t.definition.sources) for t in origins)):
                    raise ValueError("source task is not the unique unfinished task of this workflow instruction")
                _verify_task_scope(issuer_handle, caller,
                    _task_scope(issuer, run_id, source, workflow, release, ledger, task),
                    fields.get("task_scope_delegation_id", ""))
                validate_instruction_sources(tx, source, task.definition.sources, definition=task.definition)
                from neurath.providers.waves import pending
                from scripts.agent_harness.delegation_wave import require_complete
                if pending(root, session_id=str(source.session.id), actor_id=str(handle.actor_id),
                           task_id=task.id, db=tx.connection):
                    raise ValueError("source task has unsettled provider waves")
                journal = tx.get("host-journal", str(source.session.id))
                if journal:
                    require_complete(json.loads(journal.payload), source, task.id)
                evidence = tuple(fields["evidence"])
                # Receipt-bearing labels come from the trusted producer, not issuer prose.
                protected = {"root_checkout_cleanup_receipt", "workflow_state_merged", "process_state_merged",
                             "adaptive_control_receipt"}
                if any(item.partition(":")[0].strip() in protected for item in evidence):
                    raise ValueError("receipt evidence is generated from the persisted producer")
                evidence += ("root_checkout_cleanup_receipt: " + canonical(cleanup),
                    "process_state_merged: state=MERGED pr_number=" + str(merged["pr_number"])
                    + " merge_commit_oid=" + merged["merge_commit_oid"],
                    "workflow_state_merged: " + canonical(merged),
                    "adaptive_control_receipt: " + canonical(proof.receipt.to_evidence()))
                runner = PhaseRunner(SkillContractRepository(root))
                runner.complete(store, phase.current_phase_id, "completed", evidence,
                                "Issuer recovered terminal bookkeeping from the exact cleanup receipt.", None)
                runner.finalize(store, "merged")
                proposed = handle.inspect().workflows[workflow_id]
                from scripts.agent_harness.session_kernel import PostCleanupFinalized
                admission = {"issuer": issuer, "issuer_actor": str(issuer_handle.actor_id),
                    "issuer_session": str(caller.session.id), "issuer_revision": caller.revision,
                    "source_session": str(source.session.id), "source_revision": source.revision,
                    "original_owner": str(workflow.owner_actor_id), "workflow_id": workflow_id,
                    "workflow_revision": workflow.revision, "run_id": run_id,
                    "worker_generation": result["worker_generation"], "worktree_id": cleanup["worktree_id"],
                    "release_digest": release["reference"].rsplit(":", 1)[-1],
                    "payload_digest": hashlib.sha256(canonical(dict(proposed.payload)).encode()).hexdigest()}
                encoded = canonical(admission).encode()
                admission_reference = hashlib.sha256(encoded).hexdigest()
                tx.put("post-cleanup-admission", admission_reference, encoded, expected_revision=None)
                final_state = kernel.finalize_cleaned_transaction(tx, PostCleanupFinalized(session_id=source.session.id,
                    workflow_id=WorkflowId(workflow_id), actor_id=issuer_handle.actor_id,
                    original_owner=workflow.owner_actor_id, expected_workflow_revision=workflow.revision,
                    payload=proposed.payload, admission_reference=admission_reference,
                    idempotency_key="post-cleanup:" + issuer + ":" + fields["key"]),
                    expected_revision=source.revision)
                final = final_state.workflows[workflow_id]
                report = {"schema": "neurath.task-result.v1", "task_id": task.id,
                    "definition_digest": task.definition.digest, "status": "succeeded",
                    "summary": fields["summary"], "assurance": "agent-report",
                    "actor_id": str(issuer_handle.actor_id), "owner_actor_id": ledger.owner,
                    "performed_by": issuer,
                    "result_references": [release["reference"], "workflow:" + workflow_id],
                    "recovery": {"run_id": run_id, "original_owner": ledger.owner,
                        "task_scope_delegation_id": fields.get("task_scope_delegation_id", ""),
                        "source_revision": workflow.revision, "workflow_revision": final.revision,
                        "adaptive_goal_fingerprint": proof.goal_fingerprint}}
                artifact = SessionArtifactStore(handle).put_json(report)
                def resolve_result(selected, refs):
                    return TaskEvidence(status=TaskStatus.SUCCEEDED, subject=selected.id,
                        owner=ledger.owner, definition_digest=selected.definition.digest,
                        producer=selected.definition.producer, references=refs,
                        source_basis=artifact.reference, payload_digest=artifact.reference.removeprefix("sha256:"),
                        reason=fields["summary"])
                completed = ledger.resolve(task.id, expected_revision=fields["expected_list_revision"],
                    expected_task_revision=fields["expected_task_revision"], key="post-cleanup:" + fields["key"],
                    references=tuple(report["result_references"]), resolver=resolve_result)
                tx.put("task-ledger", str(source.session.id), completed.encode(), expected_revision=record.revision)
                outcome = {"status": "finalized", "issuer": issuer, "source_session": str(source.session.id),
                    "original_owner": ledger.owner, "run_id": run_id, "workflow_id": workflow_id,
                    "workflow_revision": final.revision, "workflow_status": final.status.value,
                    "terminal_state": "merged", "task_id": task.id, "task_list_revision": completed.revision,
                    "task_result": artifact.reference, "release_reference": release["reference"],
                    "cleanup_repeated": False}
                tx.put(namespace, fields["key"], canonical({"request": request, "result": outcome}).encode(),
                       expected_revision=None)
                return outcome
    finally:
        os.close(fd)

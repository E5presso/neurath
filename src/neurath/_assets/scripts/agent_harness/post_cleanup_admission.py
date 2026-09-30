"""Kernel admission for one explicitly issuer-authenticated cleanup finalization."""
import hashlib
import json

from scripts.agent_harness.runtime_database import RuntimeDatabase
from scripts.agent_harness.session_model import TransitionRejected


def cleanup_preserves_candidate(handle, workflow, artifact):
    """Accept only exact evaluated bytes plus authenticated cleanup bookkeeping.

    Legacy cleanup adds an intent and replaces it with a receipt (two revisions).
    Reconstructing the pre-cleanup *hash input* is safe only when it exactly matches
    the immutable evaluator candidate; no workflow or evaluator state is rewritten.
    """
    from scripts.agent_harness.session_kernel import SessionLocator, SessionStateStore
    from scripts.agent_harness.worktree_registry import WorktreeRegistry, WorktreeId
    import copy
    root = handle._repository_control_root()
    locator = SessionLocator(root)
    with RuntimeDatabase(root).transaction() as tx:
        persisted = SessionStateStore(locator.locate(handle.session_id).process_state).read_transaction(
            tx, handle.session_id).workflows.get(workflow.id)
        if (persisted is None or persisted.kind != "process-ticket"
                or persisted.owner_actor_id != handle.actor_id
                or persisted.revision != artifact.target_workflow_revision + 2):
            return False
        basis = copy.deepcopy(dict(persisted.payload))
        cleanup = basis.get("skill_state", {}).pop("merge_cleanup_receipt", None)
        if not isinstance(cleanup, dict) or cleanup.get("schema_version") != 3:
            return False
        if "merge_cleanup_intent" in basis["skill_state"]:
            return False
        release = WorktreeRegistry(locator).release_receipt_transaction(tx, WorktreeId(cleanup["worktree_id"]))
        if release is None or release["kind"] != "cleanup":
            return False
        claim = release["claim"]
        if (claim["session_id"] != str(handle.session_id) or claim["actor_id"] != str(handle.actor_id)
                or cleanup.get("owner_session_id") != claim["session_id"]
                or cleanup.get("owner_actor_id") != claim["actor_id"]
                or cleanup.get("worktree") != claim["path"]
                or cleanup.get("released_lease_epoch") != claim["lease_epoch"]
                or cleanup.get("cleanup_reservation_fencing_token_sha256") !=
                   hashlib.sha256(claim["fencing_token"].encode()).hexdigest()
                or any(cleanup.get(key) is not True for key in (
                    "worktree_removed", "branch_removed", "worktree_claim_released"))):
            return False
        encoded = json.dumps(basis, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        if hashlib.sha256(encoded).hexdigest() != artifact.target_workflow_payload_digest:
            return False
        # Staged terminal validation may change only the final phase. All evaluated
        # source authority, instructions and prior evidence remain byte-identical.
        current = copy.deepcopy(dict(workflow.payload))
        if current == dict(persisted.payload):
            return True
        old_phase, new_phase = persisted.payload.get("phase_run", {}), current.get("phase_run", {})
        if (workflow.revision != persisted.revision + 1
                or not old_phase.get("phases") or old_phase["phases"][-1]["name"] != "merge_cleanup"
                or old_phase["phases"][:-1] != new_phase.get("phases", [])[:-1]
                or new_phase.get("current_phase_id") is not None
                or new_phase.get("terminal_state") is not None
                or new_phase["phases"][-1]["status"] != "completed"):
            return False
        current["phase_run"] = old_phase
        return current == dict(persisted.payload)


def verify_admission(locator, state, event):
    """Require the application's exact transactional admission, not event assertions."""
    with RuntimeDatabase(locator.control_root).transaction() as tx:
        record = tx.get("post-cleanup-admission", event.admission_reference)
        if record is None or hashlib.sha256(record.payload).hexdigest() != event.admission_reference:
            raise TransitionRejected("post-cleanup issuer admission is missing")
        proof = json.loads(record.payload)
        from scripts.agent_harness.session_kernel import SessionId, SessionStateStore
        issuer_id = SessionId(proof["issuer_session"])
        issuer = SessionStateStore(locator.locate(issuer_id).process_state).read_transaction(tx, issuer_id)
        if (issuer.revision != proof["issuer_revision"] or str(issuer.session.root_actor_id) != str(event.actor_id)
                or proof["issuer"] != f"{issuer.session.runtime.value}:{issuer.session.id}"):
            raise TransitionRejected("post-cleanup actual issuer authority changed")
        workflow = state.workflows[event.workflow_id]
        if (proof["source_session"] != str(state.session.id)
                or proof["source_revision"] != state.revision
                or proof["workflow_id"] != str(event.workflow_id)
                or proof["workflow_revision"] != workflow.revision
                or proof["original_owner"] != str(event.original_owner)
                or proof["issuer_actor"] != str(event.actor_id)
                or proof["payload_digest"] != hashlib.sha256(json.dumps(dict(event.payload),
                    sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()):
            raise TransitionRejected("post-cleanup admission differs from the exact source")
        job = tx.connection.execute("SELECT owner,result,cancel_requested FROM provider_jobs WHERE id=?",
                                    (proof["run_id"],)).fetchone()
        if not job or job["owner"] != proof["issuer"] or job["cancel_requested"]:
            raise TransitionRejected("post-cleanup provider issuer changed")
        result = json.loads(job["result"])
        lease = tx.connection.execute("SELECT generation,state FROM provider_worker_leases WHERE run_id=?",
                                      (proof["run_id"],)).fetchone()
        if (result["created"]["native_session"] != proof["source_session"]
                or result["worker_generation"] != proof["worker_generation"]
                or lease is None or lease["generation"] != proof["worker_generation"]
                or lease["state"] == "accepted"):
            raise TransitionRejected("post-cleanup worker generation changed")
        released = tx.get("worktree", proof["worktree_id"])
        if released is None or hashlib.sha256(released.payload).hexdigest() != proof["release_digest"]:
            raise TransitionRejected("post-cleanup release fence changed")

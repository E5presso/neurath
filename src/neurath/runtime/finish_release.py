"""Narrow post-release admission for the exact finish-session terminal record."""
import hashlib
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

from neurath.memory.store import canonical


def _digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def _phase(workflow):
    from scripts.skill_harness.phase_runner import PhaseRunState
    return PhaseRunState.from_payload(dict(workflow.payload.get("phase_run", {})))


def _prefix(phase):
    prefix = [item for item in phase.phases if item.id < 6]
    if [item.id for item in prefix] != [1, 2, 3, 4, 5] or any(item.status != "completed" for item in prefix):
        raise ValueError("finish prerequisites are not completed")
    return _digest([asdict(item) for item in prefix])


def capture_finish_context(root, handle):
    from neurath.runtime.phase_evidence import _basis, _git
    state = handle.inspect()
    candidates = []
    for workflow in state.workflows.values():
        if (workflow.kind == "finish-session" and workflow.owner_actor_id == handle.actor_id
                and workflow.status.value == "active"):
            phase = _phase(workflow)
            if phase.current_phase_id == 6:
                candidates.append((workflow, phase))
    if not candidates:
        return None  # Ordinary claim release grants no finish-workflow admission.
    if len(candidates) != 1:
        raise ValueError("multiple finish workflows make release ambiguous")
    workflow, phase = candidates[0]
    if phase.north_star != workflow.goal or phase.phase(6).name != "worktree_release":
        raise ValueError("finish workflow identity changed")
    return {"schema": "neurath.finish-release.v1", "workflow_id": str(workflow.id),
            "goal": workflow.goal, "phase_digest": _digest(dict(workflow.payload["phase_run"])),
            "prefix_digest": _prefix(phase), "head": _git(root, "rev-parse", "HEAD"),
            "branch": _git(root, "branch", "--show-current"), "source_fingerprint": _basis(root)}


def _validate(root, handle, registry, worktree_id, name, fields):
    from neurath.runtime.phase_evidence import _basis, _git
    allowed = {"phase_evidence_prepare", "phase_complete", "phase_finalize",
               "workflow_advance", "workflow_finalize"}
    if name not in allowed:
        raise ValueError("post-release admission is restricted to finish metadata")
    receipt = registry.release_receipt(worktree_id)
    if receipt is None or receipt["kind"] != "released" or not isinstance(receipt.get("context"), dict):
        raise ValueError("current worktree has no exact finish release receipt")
    claim, context = receipt["claim"], receipt["context"]
    if (claim["session_id"] != str(handle.session_id) or claim["actor_id"] != str(handle.actor_id)
            or Path(claim["path"]).resolve() != Path(root).resolve()
            or context.get("schema") != "neurath.finish-release.v1"
            or context.get("workflow_id") != fields.get("workflow_id")):
        raise ValueError("finish release receipt belongs to another owner or workflow")
    state = handle.inspect()
    workflow = state.workflows.get(fields["workflow_id"])
    if (workflow is None or workflow.kind != "finish-session"
            or workflow.owner_actor_id != handle.actor_id or workflow.goal != context["goal"]):
        raise ValueError("finish workflow differs from release context")
    phase = _phase(workflow)
    if _prefix(phase) != context["prefix_digest"] or phase.north_star != context["goal"]:
        raise ValueError("finish prerequisites changed after release")
    if phase.current_phase_id not in (6, None) or phase.terminal_state not in (None, "finished"):
        raise ValueError("post-release workflow is outside its terminal phase")
    if name == "phase_evidence_prepare":
        if fields.get("labels") != ["worktree_release_receipt"] or fields.get("notes"):
            raise ValueError("post-release evidence must use the actual release producer")
    elif name in {"phase_complete", "workflow_advance"}:
        transition = fields.get("transition", fields)
        if (transition.get("phase_id") != 6 or transition.get("status") != "completed"
                or transition.get("terminal_state", "") not in ("", "finished")):
            raise ValueError("only the final successful finish transition is admitted")
    elif fields.get("terminal_state") != "finished" or phase.current_phase_id is not None:
        raise ValueError("finish finalization is not ready")
    if (_git(root, "rev-parse", "HEAD") != context["head"]
            or _git(root, "branch", "--show-current") != context["branch"]
            or _basis(root) != context["source_fingerprint"]):
        raise ValueError("worktree source changed after release")
    return receipt


@contextmanager
def post_release_admission(root, handle, name, fields):
    from scripts.agent_harness.session_kernel import SessionLocator
    from scripts.agent_harness.worktree_registry import WorktreeIdentityResolver, WorktreeRegistry
    identity = WorktreeIdentityResolver().resolve(Path(root))
    registry = WorktreeRegistry(SessionLocator.from_worktree(Path(root)))
    with registry.terminal_admission(identity.worktree_id):
        _validate(root, handle, registry, identity.worktree_id, name, fields)
        class ReleaseHandle:
            def __getattr__(self, attr):
                return getattr(handle, attr)

            def inspect(self):
                _validate(root, handle, registry, identity.worktree_id, name, fields)
                return handle.inspect()

            def apply(self, event, expected_revision=None):
                _validate(root, handle, registry, identity.worktree_id, name, fields)
                return handle.apply(event, expected_revision=expected_revision)
        yield ReleaseHandle()


def release_evidence(root, handle):
    from scripts.agent_harness.session_kernel import SessionLocator
    from scripts.agent_harness.worktree_registry import WorktreeIdentityResolver, WorktreeRegistry
    identity = WorktreeIdentityResolver().resolve(Path(root))
    registry = WorktreeRegistry(SessionLocator.from_worktree(Path(root)))
    receipt = registry.release_receipt(identity.worktree_id)
    if (receipt is None or receipt["kind"] != "released"
            or receipt["claim"]["session_id"] != str(handle.session_id)
            or receipt["claim"]["actor_id"] != str(handle.actor_id)):
        raise ValueError("no actual release for this native owner")
    return (f"released=true worktree_id={identity.worktree_id} "
            f"lease_epoch={receipt['claim']['lease_epoch']} receipt={receipt['reference']}")

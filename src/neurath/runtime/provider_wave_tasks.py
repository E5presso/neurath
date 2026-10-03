"""Native admission for runtime-owned waves of ordinary provider worktree workers."""

from copy import deepcopy
import hashlib
from pathlib import Path


def definitions(text_field, count, choice, provider_fields):
    """Expose closed request schemas; native identity never comes from arguments."""
    request = deepcopy(provider_fields)
    request.pop("key")
    request["purpose"] = choice("worktree-worker", "perspective")
    request["reason"] = text_field(2400)
    request["plan_id"] = text_field(128)
    request["mode"] = {**choice("inherit"), "default": "inherit"}
    request_schema = {"type": "object", "additionalProperties": False,
                      "properties": request, "required": ["worktree", "assignment", "plan_id"]}
    entry = {"type": "object", "additionalProperties": False,
        "properties": {"entry_id": text_field(128), "depends_on": {
            "type": "array", "items": text_field(128), "maxItems": 32},
            "request": request_schema},
        "required": ["entry_id", "depends_on", "request"]}
    selector = {"wave_id": text_field(128)}
    keyed = {**selector, "key": text_field(512)}
    values = {
        "provider_wave_run": ("Validate every planned isolated worktree worker, then atomically reserve the ready set and launch all reserved work. Runtime scheduling continues independently of agent waits. Provider workers are independent peers, not native children. Admission is not completion.",
            {**keyed, "task_id": text_field(128), "expected_task_revision": count(1, 2147483647),
             "workflow_id": text_field(256, default=""),
             "entries": {"type": "array", "items": entry, "minItems": 1, "maxItems": 32},
             "max_parallel": count(2, 32), "capacity_basis": text_field(2400)}, False),
        "provider_wave_read": ("Read an owned provider wave after an event, with actual run identities and exact result digests. Reconcile durable pending launch work; never infer success from admission.", selector, False),
        "provider_wave_consume": ("Accept or reject one exact owned worker result by run, generation and digest. Accepted completion unlocks dependencies and the runtime fills ready slots. Worker output is agent-report, not independent evaluation authority.",
            {**keyed, "entry_id": text_field(128), "run_id": text_field(128),
             "generation": count(1, 2147483647), "result_digest": text_field(128),
             "verdict": choice("accepted", "rejected")}, False),
        "provider_wave_cancel": ("Cancel an owned wave and its exact provider runs through their control channels. Prevent future reservations; retain observed outcomes and unfinished user requirements.", keyed, False),
        "provider_wave_retry": ("Explicitly retry one provably ended failed implementation with fresh plan and inherited policy admission. Preserve its prior attempt and original assignment, provider and worktree. Inbox recovery is not an implementation retry.",
            {**keyed, "entry_id": text_field(128), "request": request_schema}, False),
        "provider_wave_supersede": ("Retire one terminal failed or cancelled wave only after the same owned task and issue graph have an accepted successful replacement. Preserve both wave results and never claim historical native closure.",
            {"old_wave_id": text_field(128), "new_wave_id": text_field(128),
             "key": text_field(512)}, False),
    }
    return {name: ("provider-wave", name, description, fields, readonly)
            for name, (description, fields, readonly) in values.items()}


def execute(root, name, fields, *, identity, expected_turn, verified_policy_evidence=None):
    """Keep foreground authorization separate from durable worker scheduling."""
    from neurath.providers import waves
    from neurath.runtime.task_schema import TaskError, arguments
    from neurath.runtime.admission import _verification_owner, _mcp_execution_policy
    from neurath.runtime.state_tasks import _handle
    from neurath.runtime.provider_execution import admit_wave_entry
    from neurath.runtime.model_tasks import observed_policy
    from neurath.hosts.task_scope import instruction_scope
    from neurath.serialization import canonical

    if identity is None or not identity.is_root:
        raise TaskError("native-binding-required", "provider waves require their native root owner")
    if name == "provider_wave_cancel":
        return waves.cancel(root, identity, **fields)
    before = _verification_owner(root, identity)
    _mcp_execution_policy(root, identity, expected_turn, verified_policy_evidence)
    if name == "provider_wave_read":
        return waves.read(root, identity, fields["wave_id"])
    if name == "provider_wave_consume":
        return waves.consume(root, identity, **fields)
    if name == "provider_wave_retry":
        return _retry_entry(root, fields, identity, expected_turn, verified_policy_evidence, before)
    if name == "provider_wave_supersede":
        old = waves.snapshot(root, identity, fields["old_wave_id"])
        scope = old["task_scope"]
        handle = _handle(root, identity, expected_turn, verified_policy_evidence)
        checked = instruction_scope(root, handle.inspect(), scope["task_id"], scope["task_revision"])
        if checked["definition_digest"] != scope["definition_digest"]:
            raise TaskError("revision-conflict", "supersession task definition changed")
        return waves.supersede(root, identity, **fields)

    handle = _handle(root, identity, expected_turn, verified_policy_evidence)
    state = handle.inspect()
    task_scope = instruction_scope(root, state, fields["task_id"], fields["expected_task_revision"])
    task_scope.update(session_id=str(handle.session_id), actor_id=str(handle.actor_id))
    workflow_id = fields["workflow_id"]
    if workflow_id:
        workflow = state.workflows.get(workflow_id)
        if workflow is None or workflow.owner_actor_id != handle.actor_id or workflow.status.value != "active":
            raise TaskError("authority-denied", "provider wave requires an active owned workflow")
    request_digest = "sha256:" + hashlib.sha256(canonical(fields).encode()).hexdigest()
    previous = waves.replay(root, identity, wave_id=fields["wave_id"],
                            request_digest=request_digest, key=fields["key"])
    if previous is not None:
        return previous
    for entry in fields['entries']:
        _require_execution_choice(entry['request'])
    targets = [str(Path(entry["request"]["worktree"]).resolve()) for entry in fields["entries"]]
    if len(targets) != len(set(targets)):
        raise TaskError("invalid-input", "wave workers require distinct isolated worktrees")
    policy = observed_policy(root, identity, expected_turn, verified_policy_evidence)
    admitted = []
    for entry in fields["entries"]:
        key = hashlib.sha256(canonical([fields["wave_id"], entry["entry_id"], fields["key"]]).encode()).hexdigest()
        request = arguments("provider_run", {**entry["request"],
            "key": "wave-entry:" + key})
        admitted.append({"entry_id": entry["entry_id"], "depends_on": entry["depends_on"],
                         "request": admit_wave_entry(root, identity, request, policy)})
    if _verification_owner(root, identity) != before:
        raise TaskError("native-prompt-changed", "wave admission lost its issuer before reservation")
    _mcp_execution_policy(root, identity, expected_turn, verified_policy_evidence)
    return waves.admit(root, identity, wave_id=fields["wave_id"], task_scope=task_scope,
        entries=admitted, max_parallel=fields["max_parallel"], capacity_basis=fields["capacity_basis"],
        workflow_id=workflow_id, request_digest=request_digest, key=fields["key"])


def _retry_entry(root, fields, identity, expected_turn, evidence, before):
    """Re-admit a failed implementation without confusing inbox recovery with work."""
    from neurath.providers import waves
    from neurath.runtime.task_schema import TaskError, arguments
    from neurath.runtime.admission import _verification_owner, _mcp_execution_policy
    from neurath.runtime.state_tasks import _handle
    from neurath.runtime.provider_execution import admit_wave_entry
    from neurath.runtime.model_tasks import observed_policy
    from neurath.hosts.task_scope import instruction_scope
    from neurath.serialization import canonical

    current = waves.snapshot(root, identity, fields["wave_id"])
    scope = current["task_scope"]
    handle = _handle(root, identity, expected_turn, evidence)
    checked = instruction_scope(root, handle.inspect(), scope["task_id"], scope["task_revision"])
    if checked["definition_digest"] != scope["definition_digest"]:
        raise TaskError("revision-conflict", "retry task definition changed")
    request_digest = "sha256:" + hashlib.sha256(canonical(fields).encode()).hexdigest()
    previous = waves.replay_retry(root, identity, wave_id=fields["wave_id"],
        entry_id=fields["entry_id"], request_digest=request_digest, key=fields["key"])
    if previous is not None:
        return previous
    _require_execution_choice(fields['request'])
    selected = next((entry for entry in current["entries"] if entry["entry_id"] == fields["entry_id"]), None)
    if selected is None:
        raise TaskError("invalid-input", "retry entry does not exist")
    request = arguments("provider_run", {**fields["request"],
        "key": "wave-retry:" + request_digest})
    original = selected["original_request"]
    if (request["assignment"] != original["assignment"] or request["provider"] != original["provider"]
            or Path(request["worktree"]).resolve() != Path(original["worktree"]).resolve()
            or request["purpose"] != original["purpose"]
            or request["session_basis"] != original.get("session_basis", "")
            or request["reason"] != original.get("reason", "")):
        raise TaskError("invalid-input", "retry cannot change assignment, provider, worktree or execution choice")
    policy = observed_policy(root, identity, expected_turn, evidence)
    admitted = admit_wave_entry(root, identity, request, policy)
    if _verification_owner(root, identity) != before:
        raise TaskError("native-prompt-changed", "retry admission lost its issuer")
    _mcp_execution_policy(root, identity, expected_turn, evidence)
    return waves.retry(root, identity, wave_id=fields["wave_id"], entry_id=fields["entry_id"],
                       request=admitted, request_digest=request_digest, key=fields["key"])


def _require_execution_choice(request):
    # Omitted fields remain parseable only so an exact accepted legacy request
    # can replay above. New work never receives a manufactured choice/reason.
    if not request.get('purpose') or not request.get('reason'):
        from neurath.runtime.task_schema import TaskError
        raise TaskError('invalid-input', 'new provider work requires an explicit execution choice and reason')

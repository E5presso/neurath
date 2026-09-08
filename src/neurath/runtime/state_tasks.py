"""Typed state operations; identity is accepted only from the native task dispatcher.

These operations change harness metadata. They cannot execute commands, edit
product files, widen a native policy or supply a tool completion receipt.
"""

from pathlib import Path


def definitions():
    from neurath.runtime.task_schema import choice, count, document_field, text_field

    expectation = {"type": "object", "additionalProperties": False,
        "required": ["observable_id", "expected_delta"], "properties": {
            "observable_id": text_field(4096),
            "expected_delta": choice("created", "changed", "deleted", "unchanged"),
            "expected_digest": text_field(64, default="")}}
    batch = {"batch_id": text_field(256), "expected_revision": count(0, 2**53 - 1, 0),
             "key": text_field(512)}
    # Revisions are mandatory; count's default is inappropriate for CAS input.
    batch["expected_revision"].pop("default")
    entries = {
        "artifact_put": ("Store a bounded JSON document in this native session and return its content reference. Does not grant evaluation authority or edit a caller-selected path.", {
            "document": document_field(), "key": text_field(512)}, False),
        "artifact_read": ("Read a content-addressed artifact from this native session. Reference data is not caller or evaluator authority.", {
            "reference": text_field(71)}, True),
        "session_inspect": ("Inspect this native caller's session kernel.", {}, True),
        "turn_inspect": ("Inspect this native caller's foreground turn.", {}, True),
        "worktree_inspect": ("Read the canonical current worktree claim without acquiring it.", {}, True),
        "worktree_claim": ("Claim only the current worktree for this native actor. Never force takeover.", {}, False),
        "worktree_release": ("Release this actor's claim with the exact observed lease and token.", {
            "expected_lease_epoch": {"type": "integer", "minimum": 1, "maximum": 2**53 - 1},
            "fencing_token": text_field(256)}, False),
        "material_prepare": ("Prepare exact local targets and read their baseline. Does not edit files or execute code.", {
            "batch_id": text_field(256), "kind": choice("local-mutation", "semantic-decision"),
            "targets": {"type": "array", "items": text_field(4096), "minItems": 1, "maxItems": 64},
            "expectations": {"type": "array", "items": expectation, "minItems": 1, "maxItems": 64},
            "workflow_id": text_field(256, default=""), "key": text_field(512)}, False),
        "material_read": ("Read this actor's latest material batch and actual receipts.", {}, True),
        "material_resolve": ("Resolve the exact batch revision through kernel receipt and delta checks. A requested completed resolution is not evidence.", {
            **batch, "resolution": choice("completed", "blocked", "aborted")}, False),
        "material_abandon": ("Record a lost host completion as unknown and blocked, never successful.", {
            **batch, "invocation_id": text_field(256)}, False),
    }
    return {name: ("state", name, description, fields, readonly)
            for name, (description, fields, readonly) in entries.items()}


def _handle(root, identity, expected_turn, context):
    from neurath.memory.store import canonical
    from neurath.runtime.engine import activate
    from neurath.runtime.task_schema import TaskError

    activate(root)
    from scripts.agent_harness.session_kernel import (
        ActorId,
        SessionId,
        SessionLocator,
        SessionRuntime,
    )
    from scripts.agent_harness.state_handle import RuntimeIdentityBinding, StateHandle

    from neurath.agents.hooks import participation
    from neurath.agents.mcp import _prompt_receipt
    from neurath.hosts.identity import _state, active_connection

    if identity is None or expected_turn is None:
        raise TaskError("native-binding-required", "state tasks require a current native tool invocation")
    state = _state(root, identity.session)
    actor = state.actors.get(ActorId(identity.actor))
    if (actor is None or participation(state, actor) != (True, expected_turn)
            or not active_connection(root, identity.session)):
        raise TaskError("native-turn-changed", "state task no longer has its active native turn")
    if (context is None or "user_prompt_receipt" not in context
            or canonical(context["user_prompt_receipt"]) != canonical(_prompt_receipt(state, actor))):
        raise TaskError("native-prompt-changed", "state task no longer has its native user prompt")
    if identity.is_root != (str(state.session.root_actor_id) == identity.actor):
        raise TaskError("authority-denied", "native root identity differs from the session")
    binding = RuntimeIdentityBinding(runtime=SessionRuntime(identity.host),
        session_id=SessionId(identity.session), actor_id=ActorId(identity.actor),
        root_actor_id=state.session.root_actor_id)
    return StateHandle.attach(SessionLocator.from_worktree(root), binding)


def execute(root, name, fields, *, identity, expected_turn, verified_policy_evidence=None):
    from neurath.runtime.engine import activate
    from neurath.runtime.task_schema import TaskError

    activate(root)
    from scripts.agent_harness.session_kernel import SessionLocator
    from scripts.agent_harness.worktree_registry import (
        WorktreeClaim,
        WorktreeIdentityResolver,
        WorktreeNotClaimed,
        WorktreeRegistry,
    )

    # The dispatcher has validated the closed input schema and native capability.
    root = Path(root).resolve()
    handle = _handle(root, identity, expected_turn, verified_policy_evidence)
    state = handle.inspect()
    if name in {"artifact_put", "artifact_read"}:
        from scripts.agent_harness.artifact_store import SessionArtifactStore
        artifacts = SessionArtifactStore(handle)
        if name == "artifact_read":
            return {"reference": fields["reference"], "document": artifacts.read_json(fields["reference"])}
        _reserve_key(root, identity, name, fields)
        receipt = artifacts.put_json(fields["document"])
        return {"reference": receipt.reference, "media_type": receipt.media_type, "size_bytes": receipt.size_bytes}
    if name == "session_inspect":
        return state.to_payload()
    if name == "turn_inspect":
        return state.foreground_turns[handle.actor_id].to_payload()
    if name == "material_read":
        batch = state.material_actions.get(handle.actor_id)
        return {"batch": None if batch is None else batch.to_payload()}
    canonical = WorktreeIdentityResolver().resolve(root)
    registry = WorktreeRegistry(SessionLocator.from_worktree(root))
    if name == "worktree_claim":
        return registry.claim(WorktreeClaim(worktree_id=canonical.worktree_id,
            path=canonical.path, session_id=handle.session_id, actor_id=handle.actor_id)).to_payload()
    try:
        claim = registry.get(canonical.worktree_id)
    except WorktreeNotClaimed:
        if name == "worktree_inspect":
            return {"worktree_id": str(canonical.worktree_id), "claim": None}
        raise TaskError("claim-required", "state mutation requires the current worktree claim") from None
    if name == "worktree_inspect":
        return {"worktree_id": str(canonical.worktree_id), "claim": claim.to_payload()}
    if (claim.path != canonical.path or claim.session_id != handle.session_id
            or claim.actor_id != handle.actor_id or claim.status.value != "active"):
        raise TaskError("authority-denied", "current native actor does not own this worktree claim")
    if name == "worktree_release":
        if (claim.lease_epoch != fields["expected_lease_epoch"]
                or claim.fencing_token != fields["fencing_token"]):
            raise TaskError("revision-conflict", "worktree release requires the observed lease and token")
        registry.release(claim)
        return {"claim": claim.to_payload(), "released": True}
    _reserve_key(root, identity, name, fields)
    return _material(root, canonical.path, handle, state, name, fields)


def _material(root, worktree, handle, state, name, fields):
    from scripts.agent_harness.material_action import MaterialActionKind, MaterialActionResolution
    from scripts.agent_harness.session_kernel import (
        MaterialActionAbandoned,
        MaterialActionPrepared,
        MaterialActionResolved,
    )

    from neurath.runtime.task_schema import TaskError

    common = {"session_id": handle.session_id, "actor_id": handle.actor_id,
              "batch_id": fields["batch_id"], "idempotency_key": "task:" + name + ":" + fields["key"]}
    turn = state.foreground_turns[handle.actor_id]
    if name == "material_prepare":
        current = state.material_actions.get(handle.actor_id)
        original = current if current is not None and current.batch_id == fields["batch_id"] else None
        targets, expectations = _expectations(root, worktree, fields, original)
        binding = None
        if fields["workflow_id"]:
            from scripts.agent_harness.adaptive_control_store import AdaptiveControlStore
            from scripts.agent_harness.material_action import AdaptiveActionBinding
            from scripts.agent_harness.session_kernel import WorkflowId
            from scripts.agent_harness.skill_state_store import SkillStateStore
            workflow_id = WorkflowId(fields["workflow_id"])
            snapshot = AdaptiveControlStore(SkillStateStore(handle, workflow_id)).read()
            binding = AdaptiveActionBinding(workflow_id=str(workflow_id),
                workflow_revision=snapshot.workflow_revision, goal_fingerprint=snapshot.state.contract.fingerprint)
        kind = MaterialActionKind(fields["kind"])
        if kind is MaterialActionKind.SEMANTIC_DECISION and binding is None:
            raise TaskError("authority-denied", "semantic decision requires workflow adaptive authority")
        current = state.material_actions.get(handle.actor_id)
        sequence = (1 if current is None else current.sequence
                    if current.batch_id == fields["batch_id"] else current.sequence + 1)
        event = MaterialActionPrepared(**common, sequence=sequence,
            expected_turn_generation=turn.generation, expected_turn_revision=turn.revision,
            kind=kind, targets=targets, expectations=expectations, adaptive_binding=binding)
    elif name == "material_resolve":
        event = MaterialActionResolved(**common, expected_batch_revision=fields["expected_revision"],
            resolution=MaterialActionResolution(fields["resolution"]))
    elif name == "material_abandon":
        event = MaterialActionAbandoned(**common, expected_batch_revision=fields["expected_revision"],
            expected_turn_generation=turn.generation, invocation_id=fields["invocation_id"])
    else:
        raise TaskError("invalid-input", "unsupported state operation")
    committed = handle.apply(event, expected_revision=state.revision)
    return committed.material_actions[handle.actor_id].to_payload()


def _expectations(root, worktree, fields, original=None):
    from scripts.agent_harness.material_action import (
        ObservableDeltaKind,
        ObservableExpectation,
        canonical_material_target,
        material_observable_digest,
    )

    from neurath.runtime.task_schema import TaskError

    def path(value):
        candidate = Path(value)
        target = canonical_material_target(candidate if candidate.is_absolute() else root / candidate)
        if not target.is_relative_to(worktree) or (
                (target.exists() or target.is_symlink()) and not (target.is_file() or target.is_symlink())):
            raise TaskError("invalid-input", "material target must be a file inside the current worktree")
        return str(target)

    targets = tuple(sorted(path(value) for value in fields["targets"]))
    if not targets or len(targets) != len(set(targets)):
        raise TaskError("invalid-input", "material targets must be nonempty and unique after canonicalization")
    expectations = []
    for item in fields["expectations"]:
        target = path(item["observable_id"])
        delta = ObservableDeltaKind(item["expected_delta"])
        expected = item.get("expected_digest") or None
        if expected is not None and (len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected)):
            raise TaskError("invalid-input", "expected digest must be lowercase SHA-256")
        saved = {} if original is None else {item.observable_id: item.baseline_digest for item in original.expectations}
        baseline = saved[target] if target in saved else material_observable_digest(Path(target))
        if ((delta is ObservableDeltaKind.CREATED and baseline is not None)
                or (delta is ObservableDeltaKind.DELETED and (baseline is None or expected is not None))
                or (delta is ObservableDeltaKind.CHANGED and (baseline is None or baseline == expected))
                or (delta is ObservableDeltaKind.UNCHANGED and (baseline is None or expected not in (None, baseline)))):
            raise TaskError("invalid-input", "declared material delta conflicts with the observed baseline")
        expectations.append(ObservableExpectation(observable_id=target, baseline_digest=baseline,
            expected_delta=delta, expected_digest=expected))
    observables = [item.observable_id for item in expectations]
    if len(observables) != len(set(observables)) or set(observables) != set(targets):
        raise TaskError("invalid-input", "targets and observable expectations must match exactly")
    return targets, tuple(sorted(expectations, key=lambda item: item.observable_id))


def _reserve_key(root, identity, name, fields):
    """A key fixes the input; interruption leaves the typed engine operation replayable."""
    from neurath.agents.store import MessageStore
    from neurath.memory.store import canonical
    from neurath.runtime.task_schema import TaskError

    request = canonical({"worktree": str(root), "input": fields})
    with MessageStore(root).connection() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS state_task_requests (
            actor TEXT NOT NULL, operation TEXT NOT NULL, key TEXT NOT NULL, request TEXT NOT NULL,
            PRIMARY KEY(actor, operation, key))""")
        prior = db.execute("SELECT request FROM state_task_requests WHERE actor=? AND operation=? AND key=?",
            (identity.address, name, fields["key"])).fetchone()
        if prior is not None and prior["request"] != request:
            raise TaskError("idempotency-conflict", "state task key already identifies different input")
        db.execute("INSERT OR IGNORE INTO state_task_requests VALUES (?,?,?,?)",
            (identity.address, name, fields["key"], request))

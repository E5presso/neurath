"""Named workflow operations over native handles and existing typed domain stores."""

import json
from pathlib import Path


def _object(fields, *, optional=()):
    return {"type": "object", "additionalProperties": False, "properties": fields,
            "required": [key for key in fields if key not in optional]}


def _array(item):
    return {"type": "array", "items": item, "maxItems": 128}


def _nullable(schema):
    return {"anyOf": [schema, {"type": "null"}]}


def adaptive_schema():
    """Closed current codec vocabulary; domain codec also checks cross-record invariants."""
    try:
        from scripts.agent_harness import adaptive_control as ac
        from scripts.agent_harness import efficiency_assessment as ef
    except ModuleNotFoundError:
        from neurath.runtime.engine import activate
        activate()
        from scripts.agent_harness import adaptive_control as ac
        from scripts.agent_harness import efficiency_assessment as ef

    from neurath.runtime.task_schema import choice, text_field

    text = text_field(16000, default="")
    integer = {"type": "integer", "minimum": 0, "maximum": 2**53 - 1}
    number = {"type": "number"}
    boolean = {"type": "boolean"}
    strings = _array(text)
    def enum(cls):
        return choice(*(item.value for item in cls))
    lineage = _object({"authority": enum(ac.EvidenceAuthority), "issuer_id": text,
        "subject_id": text, "intent_revision": integer, "source_revision": text,
        "receipt_digest": text, "delegation_id": _nullable(text)})
    criterion = _object({**{key: text for key in ("criterion_id", "description", "source_requirement_id",
        "approved_requirement_fingerprint", "observer", "precondition", "stimulus", "expected_outcome")},
        "oracle_owner": enum(ac.OracleOwner), "hard": boolean, "required_evidence": _array(enum(ac.EvidenceKind))})
    contract = _object({"goal": text, "constraints": strings, "requirement_ids": strings,
        "criteria": _array(criterion), "non_goals": strings, "intent_revision": integer, "source_revision": text})
    deferral = _object({"gap_id": text, "intent_revision": integer, "reason": text,
        "lineage": lineage, "decision_reference": _nullable(text)})
    gap = _object({**{key: text for key in ("gap_id", "context", "question", "consequence", "recommendation", "recommendation_rationale")},
        "section": enum(ac.RequirementSection), "authority": enum(ac.GapAuthority),
        "dependency_rank": integer, "weight": number, "blocking": boolean, "reversible": boolean,
        "scope_local": boolean, "intent_revision": integer, "resolution": enum(ac.GapResolution),
        "evidence_reference": _nullable(text), "resolution_lineage": _nullable(lineage), "deferral": _nullable(deferral)})
    inventory = _object({"intent_revision": integer, "source_revision": text,
        "assessed_sections": _array(enum(ac.RequirementSection)), "gaps": _array(gap)})
    evidence = _object({"goal_fingerprint": text, "criterion_id": text, "kind": enum(ac.EvidenceKind),
        "authority": enum(ac.EvidenceAuthority), "status": enum(ac.EvidenceStatus), "reference": text,
        "lineage": lineage, "evaluation_revision": integer})
    coverage = _object({"goal_fingerprint": text, "criterion_ids": strings,
        "authority": enum(ac.EvidenceAuthority), "status": enum(ac.EvidenceStatus), "reference": text,
        **{key: number for key in ("goal_alignment", "semantic_drift", "uncertainty", "reward_hacking_risk")},
        "lineage": lineage, "evaluation_revision": integer})
    readback = _object({**{key: text for key in ("goal_fingerprint", "evidence_basis_fingerprint", "authority_source_id", "readback_reference", "receipt_digest")},
        "evaluation_revision": integer, **{key: strings for key in ("settled_evidence_units", "failed_evidence_units", "reopened_evidence_units", "open_blocker_ids")}})
    metric = _object({"status": enum(ef.ResourceTelemetryStatus), "value": _nullable(integer),
        **{key: _nullable(text) for key in ("source_id", "receipt_reference", "receipt_digest")}})
    resource = _object({"basis_fingerprint": text, **{key: metric for key in ("wall_clock_milliseconds", "tool_invocations", "input_tokens", "output_tokens", "evaluator_generations")}})
    efficiency = _object({"goal_delta": _object({"before": readback, "after": readback}),
        "resource_delta": resource, "status": enum(ef.EfficiencyStatus), "reason": text})
    observation = _object({"goal_fingerprint": text, "generation": integer, "output_fingerprint": text,
        "active_criteria": strings, "root_causes": strings, "progress": number, "material_change": boolean,
        "reproducible_harness_gap": boolean, "recovery_epoch": integer, "efficiency_assessment": _nullable(efficiency)})
    claim = _object({**{key: text for key in ("workflow_id", "source_goal_fingerprint", "source_revision", "question_digest", "prompt_digest", "prompt_reference", "target_id", "value_summary_digest", "result_goal_fingerprint", "result_source_revision")},
        **{key: integer for key in ("question_workflow_revision", "source_intent_revision", "question_generation", "question_turn_revision", "prompt_generation", "prompt_turn_revision", "result_intent_revision")},
        "target_kind": enum(ac.UserDecisionTarget), "disposition": enum(ac.UserDecisionDisposition)})
    decision = _object({"claim": claim, "decision_digest": text, "interpretation_lineage": lineage})
    return _object({"schema_version": {"type": "integer", "enum": [5]}, "contract": contract,
        "inventory": inventory, "evidence": _array(evidence), "coverage": _nullable(coverage),
        "execution_status": enum(ac.ExecutionStatus), "observations": _array(observation), "user_decisions": _array(decision)})


def definitions():
    from neurath.runtime.phase_evidence import schema as evidence_schema
    from neurath.runtime.task_schema import choice, strings, text_field
    workflow = {"workflow_id": text_field(256)}
    key = {"key": text_field(512)}
    revision = {"expected_revision": {"type": "integer", "minimum": 0, "maximum": 2**53 - 1}}
    phase = {"phase_id": {"type": "integer", "minimum": 0, "maximum": 1000},
        "status": choice("completed", "skipped", "failed", "blocked"),
        "summary": text_field(), "reason": text_field(default=""),
        "terminal_state": text_field(128, default=""),
        "evidence_refs": {**strings(), "description": "Use the reference returned by phase_evidence_prepare, adaptive_control_initialized, adaptive_control_receipt, or delegation:<consumed-delegation-id>. The server resolves registered evidence and existing authority; raw evidence strings are rejected."}}
    terminal = {"terminal_state": text_field(128)}
    adaptive = adaptive_schema()
    assignment = _object({**{name: text_field() for name in ("candidate_ref", "goal_fingerprint", "kind", "source_revision", "trajectory_digest", "target_workflow_payload_digest", "workflow_id", "workflow_payload_digest")},
        **{name: {"type": "integer", "minimum": 0} for name in ("intent_revision", "target_workflow_revision", "workflow_revision")}})
    entries = {
        "workflow_start": ({**workflow, **key, "kind": text_field(128), "goal": text_field(),
            "initial_state": _object({"run_id": text_field(256)})}, False),
        "workflow_advance": ({**workflow, **revision, **key, "transition": _object(phase, optional=("reason", "evidence_refs", "terminal_state"))}, False),
        "workflow_finalize": ({**workflow, **revision, **key, **terminal}, False),
        "phase_start": ({**workflow, **key, "skill": text_field(128), "run_id": text_field(256), "north_star": text_field()}, False),
        "phase_current": (workflow, True),
        "phase_evidence_prepare": (evidence_schema(), False),
        "phase_complete": ({**workflow, **revision, **key, **phase}, False),
        "phase_finalize": ({**workflow, **revision, **key, **terminal}, False),
        "adaptive_read": (workflow, True),
        "adaptive_preflight": ({"workflow_id": text_field(256, default="")}, True),
        "adaptive_replace": ({**workflow, **revision, **key, "state": adaptive}, False),
        "adaptive_override_goal": ({**workflow, **revision, **key, "state": adaptive}, False),
        "delegation_prepare": ({"delegation_id": text_field(128), "assignment": text_field(8192), **key}, False),
        "delegation_assign": ({**workflow, "delegation_id": text_field(128), "assignment": text_field(8192), "target": text_field(512), **key}, False),
        "evaluation_prepare": ({**workflow, **key, "state": adaptive}, False),
        "evaluation_read": ({**workflow, "assignment": assignment}, True),
        "evaluation_execute": ({**workflow, **key, "state": adaptive, "criterion_id": text_field(256),
            "evidence_kind": choice("example-test", "property-test", "metamorphic-test", "mutation-test"), "pytest_node": text_field(4096)}, False),
        "evaluation_report": ({"delegation_id": text_field(128), **key, "verdict": text_field(128), "summary": text_field(),
            "outcome_ref": text_field(4096), "blocking_findings": strings()}, False),
        "evaluation_consume": ({"delegation_id": text_field(128), **key}, False),
    }
    descriptions = {
        "workflow_start": "Start a registered skill workflow from its typed phase initial state; arbitrary workflow payloads are not accepted.",
        "workflow_advance": "Apply a typed phase transition to the exact workflow revision.",
        "workflow_finalize": "Finalize a registered phase workflow only through its existing terminal and adaptive gates.",
        "phase_start": "Initialize a registered skill and enforce native evaluator prerequisites before creating state.",
        "phase_current": "Read the current phase, evidence requirements and workflow revision without mutation.",
        "phase_complete": "Resolve evidence references, enforce existing phase requirements and apply one revision-bound transition. Semantic checks preserve native execution policy.",
        "phase_finalize": "Enforce registered terminal checks, adaptive authority and native execution policy before finalization.",
        "adaptive_read": "Read typed adaptive state, derived receipt and independently verified current authority together.",
        "adaptive_preflight": "Inspect registered independent-evaluator admission without creating a workflow.",
        "adaptive_replace": "Validate a complete adaptive state and its external evidence against the exact workflow revision before replacement.",
        "adaptive_override_goal": "Apply a typed goal override only after validating current native user-intent authority; input text is not user approval.",
        "delegation_prepare": "Bind an intent for the next native child spawn. Does not spawn or attest a child, grant authority or claim a worktree.",
        "delegation_assign": "Assign an active owned workflow task to an already discovered host-attested direct child. Use collaboration_assign for independent peer sessions.",
        "evaluation_prepare": "Persist an immutable adaptive candidate and return its authenticated structured evaluator assignment.",
        "evaluation_read": "Read an immutable candidate as the actual assigned native evaluator; resolve its exact prepared assignment and digest.",
        "evaluation_execute": "Run an existing tracked pytest node through the authoritative execution receipt service under the current native policy. No arbitrary shell command input.",
        "evaluation_report": "Report as the genuine assigned native evaluator; outcome_ref is an existing detailed result reference. This report does not accept its own result.",
        "evaluation_consume": "Consume a reported delegation as its actual owner; independent evidence is authenticated by existing downstream evaluation gates.",
    }
    descriptions["phase_evidence_prepare"] = "Prepare immutable evidence for the exact current phase. Select Git facts with labels and provide other contract evidence as explicit agent-report notes. Existing authority validators still apply; preparation is not completion."
    return {name: ("workflow-task", name, descriptions[name], fields, readonly)
        for name, (fields, readonly) in entries.items()}


def execute(root, name, fields, *, identity, expected_turn, verified_policy_evidence=None):
    from neurath.runtime.engine import activate
    from neurath.runtime.state_tasks import _handle
    activate(root)
    handle = _guarded_handle(root, _handle(root, identity, expected_turn, verified_policy_evidence),
                             identity, expected_turn, verified_policy_evidence)
    reads = {"phase_current", "adaptive_read", "adaptive_preflight", "evaluation_read"}
    if name not in reads | {"evaluation_report", "evaluation_consume", "delegation_prepare"}:
        _require_owner(root, handle)
    if name in {"phase_complete", "phase_finalize", "workflow_advance", "workflow_finalize", "evaluation_execute"}:
        from neurath.runtime.tasks import _mcp_execution_policy
        _mcp_execution_policy(root, identity, expected_turn, verified_policy_evidence)
    cached = None
    if name == "phase_evidence_prepare":
        # Preparation has no external effect and validates before registering
        # its immutable result. Invalid input must not poison an execution key.
        from neurath.runtime.phase_evidence import prepare
        return prepare(root, handle, fields)
    if "key" in fields:
        cached = _request(root, identity.address, name, fields,
                          before_reserve=lambda: _preflight_start(root, name, fields, handle))
        if cached is not None:
            return cached
    result = _dispatch(root, name, fields, handle)
    if "key" in fields:
        _save(root, identity.address, name, fields["key"], result)
    return result


def _require_owner(root, handle):
    from scripts.agent_harness.session_kernel import SessionLocator
    from scripts.agent_harness.worktree_registry import WorktreeIdentityResolver, WorktreeRegistry

    from neurath.runtime.task_schema import TaskError
    canonical = WorktreeIdentityResolver().resolve(root)
    claim = WorktreeRegistry(SessionLocator.from_worktree(root)).get(canonical.worktree_id)
    if (claim.session_id != handle.session_id or claim.actor_id != handle.actor_id
            or claim.path != canonical.path or claim.status.value != "active"):
        raise TaskError("authority-denied", "this native actor does not own the worktree claim")


def _request(root, actor, name, fields, *, before_reserve=None):
    from neurath.agents.store import MessageStore
    from neurath.memory.store import canonical
    from neurath.runtime.task_schema import TaskError
    request = canonical({"root": str(Path(root).resolve()), "inputs": fields})
    with MessageStore(root).connection() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS workflow_task_requests (
            actor TEXT, operation TEXT, key TEXT, request TEXT, result TEXT,
            PRIMARY KEY(actor, operation, key))""")
        row = db.execute("SELECT request,result FROM workflow_task_requests WHERE actor=? AND operation=? AND key=?", (actor, name, fields["key"])).fetchone()
        if row is not None:
            if row["request"] != request:
                raise TaskError("idempotency-conflict", "workflow key identifies different input")
            if row["result"] is None:
                raise TaskError("outcome-unknown", "previous workflow request needs state inspection", state="failed-or-partial",
                    next_action="Read phase_current, adaptive_read or session_inspect. Reconcile the recorded operation before issuing another mutation.")
            return json.loads(row["result"])
    # Pure preflight may read other domain stores. Do not hold this write
    # transaction across those reads; recheck the exact key before reserving.
    if before_reserve is not None:
        before_reserve()
    with MessageStore(root).connection() as db:
        row = db.execute("SELECT request,result FROM workflow_task_requests WHERE actor=? AND operation=? AND key=?", (actor, name, fields["key"])).fetchone()
        if row is not None:
            if row["request"] != request:
                raise TaskError("idempotency-conflict", "workflow key identifies different input")
            if row["result"] is None:
                raise TaskError("outcome-unknown", "concurrent workflow request needs state inspection", state="failed-or-partial")
            return json.loads(row["result"])
        db.execute("INSERT INTO workflow_task_requests VALUES (?,?,?,?,NULL)", (actor, name, fields["key"], request))
    return None


def _save(root, actor, name, key, result, *, store=None):
    from neurath.agents.store import MessageStore
    from neurath.memory.store import canonical
    with (store if store is not None else MessageStore(root)).connection() as db:
        db.execute("UPDATE workflow_task_requests SET result=? WHERE actor=? AND operation=? AND key=?", (canonical(result), actor, name, key))


def _preflight_start(root, name, fields, handle):
    """Reject known pre-creation failures before reserving a side-effect key.

    The actual domain write repeats these checks. Failures after reservation keep
    their uncertain outcome; an existing completed request still replays first.
    """
    if name not in {"phase_start", "workflow_start"}:
        return
    from neurath.skill_names import source_id
    from scripts.agent_harness.evaluation_admission import EvaluationAdmissionPolicy
    from scripts.skill_harness.phase_runner import PhaseRunState, PhaseRunnerError, SkillContractRepository
    skill = source_id(fields["skill"] if name == "phase_start" else fields["kind"])
    run_id = fields["run_id"] if name == "phase_start" else fields["initial_state"]["run_id"]
    goal = fields["north_star"] if name == "phase_start" else fields["goal"]
    state = PhaseRunState.initialize(SkillContractRepository(root).get(skill), run_id, goal)
    if state.adaptive_control_required and EvaluationAdmissionPolicy().inspect(
            handle.inspect(), handle.actor_id)["status"] == "unavailable":
        raise PhaseRunnerError("EVALUATOR_UNAVAILABLE",
            "no current host-attested direct child evaluator; register the native evaluator "
            "and retry the same request; no workflow was created")


def _dispatch(root, name, fields, handle):
    from scripts.agent_harness.session_kernel import WorkflowId
    if name.startswith(("phase_", "workflow_")):
        return _phase(root, name, fields, handle)
    if name.startswith("delegation_") or name in {"evaluation_report", "evaluation_consume"}:
        return _delegation(root, name, fields, handle)
    workflow_id = WorkflowId(fields["workflow_id"]) if fields.get("workflow_id") else None
    if name == "adaptive_preflight":
        from scripts.agent_harness.evaluation_admission import EvaluationAdmissionPolicy
        return EvaluationAdmissionPolicy().inspect(handle.inspect(), handle.actor_id, workflow_id)
    if name == "adaptive_read":
        return _adaptive_read(handle, workflow_id)
    if name in {"adaptive_replace", "adaptive_override_goal"}:
        from scripts.agent_harness.adaptive_control_authority import (
            AdaptiveControlAuthorityVerifier,
        )
        from scripts.agent_harness.adaptive_control_store import (
            AdaptiveControlState,
            AdaptiveControlStore,
        )
        from scripts.agent_harness.skill_state_store import SkillStateStore
        candidate = AdaptiveControlState.from_payload(fields["state"])
        verifier = AdaptiveControlAuthorityVerifier(handle, workflow_id)
        verifier.validate_candidate(candidate, fields["expected_revision"])
        store = AdaptiveControlStore(SkillStateStore(handle, workflow_id))
        method = store.compare_and_override_payload if name == "adaptive_override_goal" else store.compare_and_replace_payload
        method(fields["expected_revision"], candidate.to_payload())
        return _adaptive_read(handle, workflow_id)
    return _evaluation(name, fields, handle, workflow_id)


def _phase(root, name, fields, handle):
    from scripts.agent_harness.session_kernel import WorkflowId
    from scripts.skill_harness.phase_runner import PhaseRunner, SkillContractRepository
    from scripts.skill_harness.session_phase_store import (
        SessionPhaseRunnerStore,
        SessionPhaseStateStore,
    )

    from neurath.runtime.task_schema import TaskError
    workflow_id = WorkflowId(fields["workflow_id"])
    runner = PhaseRunner(SkillContractRepository(root))
    if name in {"phase_start", "workflow_start"}:
        skill = fields["skill"] if name == "phase_start" else fields["kind"]
        from neurath.skill_names import source_id
        skill = source_id(skill)
        runner._repository.get(skill)  # Registered contract, never a caller supplied schema.
        run_id = fields["run_id"] if name == "phase_start" else fields["initial_state"]["run_id"]
        goal = fields["north_star"] if name == "phase_start" else fields["goal"]
        store = SessionPhaseRunnerStore(SessionPhaseStateStore(handle, workflow_id, skill, run_id))
        result = runner.initialize(skill, run_id, goal, store)
    else:
        original = SessionPhaseRunnerStore.open_existing(handle, workflow_id)
        if name == "phase_current":
            result = runner.current(original)
            return {**result, "workflow_revision": handle.inspect().workflows[workflow_id].revision}
        expected = fields["expected_revision"]
        class FencedStore(SessionPhaseRunnerStore):
            def read(self):
                state = super().read()
                if self._last_snapshot.workflow_revision != expected:
                    raise TaskError("revision-conflict", "phase requires the exact observed workflow revision")
                return state
        store = FencedStore(original._store)
        store.read()
        if name in {"phase_finalize", "workflow_finalize"}:
            result = runner.finalize(store, fields["terminal_state"])
        else:
            transition = fields["transition"] if name == "workflow_advance" else fields
            evidence = _evidence_refs(handle, workflow_id, transition.get("evidence_refs", []), root=root)
            if transition["status"] == "completed":
                required = runner.current(store)["required_evidence"]
                labels = {item.partition(":")[0].strip() for item in evidence}
                if set(required) - labels:
                    raise TaskError("invalid-evidence-reference", "each required evidence label needs its own exact structured entry")
            result = runner.complete(store, transition["phase_id"], transition["status"], evidence,
                transition["summary"], transition.get("reason") or None,
                terminal_state=transition.get("terminal_state") or None)
    return {**result, "workflow_revision": handle.inspect().workflows[workflow_id].revision}


def _evidence_refs(handle, workflow_id, references, *, root=None):
    from scripts.agent_harness.adaptive_control_store import AdaptiveControlStore
    from scripts.agent_harness.artifact_store import SessionArtifactStore
    from scripts.agent_harness.skill_state_store import SkillStateStore

    from neurath.runtime.task_schema import TaskError
    result = []
    for reference in references:
        if reference.startswith("evidence:"):
            from neurath.runtime.phase_evidence import resolve
            result.extend(resolve(root, handle, workflow_id, reference))
            continue
        if reference in {"adaptive_control_initialized", "adaptive_control_receipt"}:
            snapshot = AdaptiveControlStore(SkillStateStore(handle, workflow_id)).read()
            _adaptive_read(handle, workflow_id)  # Validate current external authority before use.
            result.append(reference + ": " + json.dumps(snapshot.receipt().to_evidence(), sort_keys=True))
            continue
        if not reference.startswith("delegation:"):
            raise TaskError("invalid-evidence-reference", "evidence must reference current adaptive authority or a consumed delegation")
        delegation = handle.inspect().delegations.get(reference.removeprefix("delegation:"))
        if (delegation is None or delegation.owner_actor_id != handle.actor_id
                or delegation.status.value != "consumed" or delegation.result is None):
            raise TaskError("authority-denied", "evidence delegation is not consumed by this owner")
        assignment = json.loads(delegation.assignment)
        if not isinstance(assignment, dict) or assignment.get("workflow_id") != str(workflow_id):
            raise TaskError("authority-denied", "evidence delegation belongs to another workflow")
        artifact = SessionArtifactStore(handle).read_json(delegation.result.outcome_ref)
        evidence = artifact.get("phase_evidence")
        if not isinstance(evidence, list) or any(not isinstance(item, str) for item in evidence):
            raise TaskError("invalid-evidence-reference", "delegation artifact has no phase_evidence string list")
        result.extend(evidence)
    return tuple(result)


def _adaptive_read(handle, workflow_id):
    from scripts.agent_harness.adaptive_control_authority import AdaptiveControlAuthorityVerifier
    from scripts.agent_harness.adaptive_control_store import AdaptiveControlStore
    from scripts.agent_harness.skill_state_store import SkillStateStore

    from neurath.runtime.task_schema import TaskError
    snapshot = AdaptiveControlStore(SkillStateStore(handle, workflow_id)).read()
    verified = AdaptiveControlAuthorityVerifier(handle, workflow_id).verify()
    if (verified.workflow_revision != snapshot.workflow_revision
            or verified.goal_fingerprint != snapshot.state.contract.fingerprint):
        raise TaskError("revision-conflict", "adaptive authority changed while reading")
    return {"workflow_id": str(workflow_id), "workflow_revision": snapshot.workflow_revision,
        "state": snapshot.state.to_payload(), "receipt": snapshot.receipt().to_evidence(),
        "authority": {"status": verified.status.value, "complete": verified.complete,
            "workflow_id": str(verified.workflow_id), "workflow_revision": verified.workflow_revision,
            "goal_fingerprint": verified.goal_fingerprint, "verified_delegation_ids": list(verified.verified_delegation_ids),
            "pending_claims": list(verified.pending_claims), "reason": verified.reason,
            "user_prompt_receipt": None if verified.user_prompt_receipt is None else verified.user_prompt_receipt.to_payload()}}


def _delegation(root, name, fields, handle):
    from scripts.agent_harness.session_kernel import (
        ActorId,
        DelegationAssigned,
        DelegationConsumed,
        DelegationId,
        DelegationReported,
        DelegationResult,
        DelegationTopologyPolicy,
        WorkflowId,
    )

    from neurath.runtime.task_schema import TaskError
    if name == "delegation_prepare":
        from neurath.hosts.identity import prepare_bound_delegation
        return prepare_bound_delegation(root, handle, fields["delegation_id"], fields["assignment"])
    state = handle.inspect()
    common = {"session_id": handle.session_id, "delegation_id": DelegationId(fields["delegation_id"]),
              "idempotency_key": "task:" + name + ":" + fields["key"]}
    if name == "delegation_assign":
        from neurath.agents.store import MessageStore
        workflow = state.workflows.get(WorkflowId(fields["workflow_id"]))
        if workflow is None or workflow.owner_actor_id != handle.actor_id or workflow.status.value != "active":
            raise TaskError("authority-denied", "assignment requires an active owned workflow")
        peers = [peer for peer in MessageStore(root).discover(fields["target"]) if peer["address"] == fields["target"]]
        if len(peers) != 1 or peers[0]["session"] != str(handle.session_id):
            raise TaskError("authority-denied", "use collaboration_assign for a separate peer session")
        event = DelegationAssigned(**common, owner_actor_id=handle.actor_id,
            target_actor_id=ActorId(peers[0]["actor"]), assignment=fields["assignment"],
            topology_policy=DelegationTopologyPolicy.DIRECT_CHILD)
    elif name == "evaluation_report":
        event = DelegationReported(**common, reporter_actor_id=handle.actor_id,
            result=DelegationResult(verdict=fields["verdict"], summary=fields["summary"],
                outcome_ref=fields["outcome_ref"], blocking_findings=tuple(fields["blocking_findings"])))
    else:
        event = DelegationConsumed(**common, consumer_actor_id=handle.actor_id)
    committed = handle.apply(event, expected_revision=state.revision)
    return committed.delegations[DelegationId(fields["delegation_id"])].to_payload()


def _evaluation(name, fields, handle, workflow_id):
    from scripts.agent_harness.adaptive_control_store import AdaptiveControlState
    from scripts.agent_harness.adaptive_evaluation_candidate import AdaptiveEvaluationCandidateStore

    from neurath.runtime.task_schema import TaskError
    store = AdaptiveEvaluationCandidateStore(handle, workflow_id)
    if name == "evaluation_prepare":
        prepared = store.prepare(AdaptiveControlState.from_payload(fields["state"]))
        return {"workflow_id": str(workflow_id), "candidate_ref": prepared.candidate_ref,
                "assignment": json.loads(prepared.assignment_json)}
    if name == "evaluation_read":
        candidate = store.read_candidate(json.dumps(fields["assignment"], sort_keys=True, separators=(",", ":")))
        return {"workflow_id": str(workflow_id), "candidate_ref": fields["assignment"]["candidate_ref"],
                "state": candidate.state.to_payload(), "trajectory": dict(candidate.trajectory)}
    if name != "evaluation_execute":
        raise TaskError("invalid-input", "unknown workflow task")
    from scripts.agent_harness.adaptive_control import EvidenceKind
    from scripts.agent_harness.adaptive_execution_receipt import AdaptiveExecutionReceiptStore
    state = AdaptiveControlState.from_payload(fields["state"])
    issued = AdaptiveExecutionReceiptStore(handle, workflow_id).execute_pytest(state.contract,
        criterion_id=fields["criterion_id"], evidence_kind=EvidenceKind(fields["evidence_kind"]), pytest_node=fields["pytest_node"])
    evidence = issued.evidence
    lineage = evidence.lineage
    return {"workflow_id": str(workflow_id), "workflow_revision": issued.workflow_revision,
        "pytest_node": issued.pytest_node, "worktree_fingerprint": issued.worktree_fingerprint,
        "evidence": {"goal_fingerprint": evidence.goal_fingerprint, "criterion_id": evidence.criterion_id,
            "kind": evidence.kind.value, "authority": evidence.authority.value, "status": evidence.status.value,
            "reference": evidence.reference, "evaluation_revision": evidence.evaluation_revision,
            "lineage": {"authority": lineage.authority.value, "issuer_id": lineage.issuer_id,
                "subject_id": lineage.subject_id, "intent_revision": lineage.intent_revision,
                "source_revision": lineage.source_revision, "receipt_digest": lineage.receipt_digest,
                "delegation_id": lineage.delegation_id}}}


def _guarded_handle(root, bound, identity, expected_turn, context, *, connection_root=None):
    """Recheck native prompt on domain reads and bind every state write to its CAS revision."""
    from neurath.agents.hooks import participation
    from neurath.agents.mcp import _prompt_receipt
    from neurath.hosts.identity import active_connection
    from neurath.memory.store import canonical
    from neurath.runtime.task_schema import TaskError

    class GuardedHandle:
        def __getattr__(self, name):
            return getattr(bound, name)

        def inspect(self):
            state = bound.inspect()
            actor = state.actors.get(bound.actor_id)
            if (actor is None or participation(state, actor) != (True, expected_turn)
                    or not active_connection(connection_root if connection_root is not None else root, identity.session)):
                raise TaskError("native-turn-changed", "workflow task lost its native turn")
            if canonical(_prompt_receipt(state, actor)) != canonical(context["user_prompt_receipt"]):
                raise TaskError("native-prompt-changed", "workflow task lost its native user prompt")
            return state

        def apply(self, event, expected_revision=None):
            state = self.inspect()
            return bound.apply(event, expected_revision=state.revision if expected_revision is None else expected_revision)

    return GuardedHandle()

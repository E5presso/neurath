"""Named context/diagnostic faces over the existing CLI domain services."""
from datetime import UTC, datetime
from pathlib import Path


def definitions():
    from neurath.runtime.task_schema import choice, text_field
    text = text_field()
    key = {"key": text_field(512)}
    loop = {"workflow_id": text_field(256), "loop_id": text_field(128)}
    finding = {"type": "object", "additionalProperties": False,
               "required": ["finding_id", "root_cause", "verdict", "reason"],
               "properties": {"finding_id": text, "root_cause": text,
                              "verdict": choice("accept", "reject", "defer"), "reason": text}}
    entries = {
        "diagnostics_integrity": ("Inspect packaged file integrity; does not attest host activation.", {}, True),
        "diagnostics_project": ("Inspect installation placement and optionally execute protocol fixtures. Protocol success is not native activation.", {
            "protocol": {"type": "boolean", "default": False}}, False),
        "diagnostics_profile": ("Inspect the installed generic profile and project document/check bindings.", {}, True),
        "enclave_read": ("Read this session's bounded current-fact snapshot and its CAS digest.", {}, True),
        "enclave_set": ("Set an agent-reported current fact using the actual native turn and observed snapshot digest; no user or harness authority is invented.", {
            "fact_key": text_field(256), "value": text, "expected_digest": text_field(64), **key}, False),
        "enclave_delete": ("Delete this root's exact fact at the observed snapshot digest.", {
            "fact_key": text_field(256), "expected_digest": text_field(64), **key}, False),
        "turn_yield": ("Record the current actor's turn outcome under its exact revision; does not bypass Stop or workflow gates.", {
            "expected_turn_revision": {"type": "integer", "minimum": 0, "maximum": 2**53-1},
            "outcome": choice("completed", "awaiting-input", "failed", "incomplete"),
            **{n: text_field(default="") for n in ("summary", "question", "reason")}, **key}, False),
        "evaluation_loop_open": ("Open a workflow-local finding loop with at least two acceptance conditions.", {
            **loop, "goal": text, "acceptance": {"type": "array", "items": text, "minItems": 2, "maxItems": 32}, **key}, False),
        "evaluation_loop_read": ("Read a workflow's exact finding loop and its receipt when closed.", loop, True),
        "evaluation_loop_round": ("Record the next numbered finding round; retain root-cause and convergence checks.", {
            **loop, "number": {"type": "integer", "minimum": 1, "maximum": 2**31-1},
            "findings": {"type": "array", "items": finding, "maxItems": 128}, **key}, False),
        "evaluation_loop_close": ("Close an evaluated finding loop only when its existing domain conditions allow the outcome.", {
            **loop, "outcome": choice("findings-clear", "approach-change-required"), "summary": text, **key}, False),
    }
    return {name: ("context", name, description, fields, readonly)
            for name, (description, fields, readonly) in entries.items()}


def execute(root, name, fields, *, identity, expected_turn, verified_policy_evidence):
    from neurath.runtime.state_tasks import _handle
    from neurath.runtime.workflow_tasks import _guarded_handle, _request, _save
    handle = _guarded_handle(root, _handle(root, identity, expected_turn, verified_policy_evidence),
                             identity, expected_turn, verified_policy_evidence)
    if name == "diagnostics_project" and fields["protocol"]:
        from neurath.runtime.tasks import _mcp_execution_policy, _verification_owner
        _verification_owner(root, identity)
        _mcp_execution_policy(root, identity, expected_turn, verified_policy_evidence)
    if "key" in fields:
        prior = _request(root, identity.address, name, fields,
                         before_reserve=lambda: _preflight(Path(root), name, fields, handle))
        if prior is not None:
            return prior
    result = _dispatch(Path(root), name, fields, handle)
    if "key" in fields:
        _save(root, identity.address, name, fields["key"], result)
    return result


def _preflight(root, name, fields, handle):
    """Validate pure candidate changes before recording a potentially effectful attempt."""
    from scripts.agent_harness.session_kernel import SessionLocator, WorkflowId, TurnId
    from neurath.runtime.task_schema import TaskError
    if name in {"enclave_set", "enclave_delete"}:
        from scripts.agent_harness.enclave_store import EnclaveFact, EnclaveSourceKind, EnclaveStore, EnclaveConflict
        store = EnclaveStore(SessionLocator.from_worktree(root), max_bytes=65536)
        store._require_root_actor(handle.session_id, handle.actor_id)
        store._validate_key(fields["fact_key"])
        current = store.read(handle.session_id)
        if current.digest != fields["expected_digest"]:
            raise EnclaveConflict(fields["expected_digest"], current.digest)
        if name == "enclave_set":
            turn = handle.inspect().foreground_turns[handle.actor_id]
            if not turn.vendor_turn_id:
                raise TaskError("native-turn-unobserved", "A native turn ID is required to record the fact")
            candidate = store._set_fact(handle.session_id, fields["fact_key"],
                EnclaveFact(value=fields["value"], source_kind=EnclaveSourceKind.AGENT,
                            source_turn_id=TurnId(turn.vendor_turn_id)), current)
        else:
            candidate = store._delete_fact(handle.session_id, fields["fact_key"], current)
        store._serialize(candidate)
    elif name.startswith("evaluation_loop_"):
        from scripts.agent_harness.evaluation_loop import EvaluationLoop, EvaluationLoopStore, Finding
        from scripts.agent_harness.skill_state_store import SkillStateStore
        state = SkillStateStore(handle, WorkflowId(fields["workflow_id"]))
        snapshot = state.read()
        now = datetime.now(UTC).isoformat()
        if name == "evaluation_loop_open":
            from scripts.agent_harness.evaluation_loop import OpenEvaluationLoopMutation
            candidate = EvaluationLoop.open(fields["loop_id"], fields["goal"], tuple(fields["acceptance"]), now)
            OpenEvaluationLoopMutation(candidate)(snapshot.skill_state)
        else:
            candidate = EvaluationLoopStore(state).read(fields["loop_id"])
            if name == "evaluation_loop_round":
                candidate.record_round(fields["number"], tuple(Finding(**f) for f in fields["findings"]), now)
            elif name == "evaluation_loop_close":
                candidate.close(fields["outcome"], fields["summary"], now)


def _dispatch(root, name, fields, handle):
    from scripts.agent_harness.session_kernel import SessionLocator, WorkflowId
    locator = SessionLocator.from_worktree(root)
    if name == "diagnostics_integrity":
        from neurath.doctor import integrity
        return integrity()
    if name == "diagnostics_project":
        from neurath.doctor import doctor
        return doctor(root, protocol=fields["protocol"])
    if name == "diagnostics_profile":
        import json
        from neurath.install.transaction import read_state
        installed = read_state(root)
        config = root / ".neurath/project.json"
        return {"installed": installed is not None,
                "profile": None if installed is None else installed["profile"],
                "bindings": json.loads(config.read_text()) if config.is_file() else None}
    if name.startswith("enclave_"):
        from scripts.agent_harness.enclave_store import EnclaveFact, EnclaveSourceKind, EnclaveStore
        from scripts.agent_harness.session_kernel import TurnId
        from neurath.runtime.task_schema import TaskError
        store = EnclaveStore(locator, max_bytes=65536)
        if name == "enclave_read":
            snapshot = store.read(handle.session_id)
        elif name == "enclave_set":
            turn = handle.inspect().foreground_turns[handle.actor_id]
            if not turn.vendor_turn_id:
                raise TaskError("native-turn-unobserved", "A native turn ID is required to record the fact")
            snapshot = store.set(handle.session_id, handle.actor_id, fields["fact_key"],
                EnclaveFact(value=fields["value"], source_kind=EnclaveSourceKind.AGENT,
                            source_turn_id=TurnId(turn.vendor_turn_id)), expected_digest=fields["expected_digest"])
        else:
            snapshot = store.delete(handle.session_id, handle.actor_id, fields["fact_key"],
                                    expected_digest=fields["expected_digest"])
        return {"digest": snapshot.digest, "snapshot": snapshot.to_payload()}
    if name == "turn_yield":
        from scripts.agent_harness.session_kernel import ForegroundTurnOutcome, ForegroundTurnReceipt, ForegroundTurnYielded
        state = handle.apply(ForegroundTurnYielded(session_id=handle.session_id, actor_id=handle.actor_id,
            expected_turn_revision=fields["expected_turn_revision"],
            receipt=ForegroundTurnReceipt(ForegroundTurnOutcome(fields["outcome"]),
                summary=fields["summary"] or None, question=fields["question"] or None, reason=fields["reason"] or None),
            idempotency_key="task:turn-yield:" + fields["key"]))
        return state.foreground_turns[handle.actor_id].to_payload()
    from scripts.agent_harness.evaluation_loop import EvaluationLoop, EvaluationLoopStore, Finding
    from scripts.agent_harness.skill_state_store import SkillStateStore
    store = EvaluationLoopStore(SkillStateStore(handle, WorkflowId(fields["workflow_id"])))
    now = datetime.now(UTC).isoformat()
    if name == "evaluation_loop_open":
        loop = store.create(EvaluationLoop.open(fields["loop_id"], fields["goal"], tuple(fields["acceptance"]), now))
    elif name == "evaluation_loop_round":
        loop = store.record_round(fields["loop_id"], fields["number"],
            tuple(Finding(**finding) for finding in fields["findings"]), now)
    elif name == "evaluation_loop_close":
        loop = store.close(fields["loop_id"], fields["outcome"], fields["summary"], now)
    else:
        loop = store.read(fields["loop_id"])
    return {**loop.to_payload(), "receipt": loop.receipt() if loop.is_closed else None}

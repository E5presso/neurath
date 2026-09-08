"""Typed execution faces over the same services and fixed scripts as the CLI."""
import json
import os
import re
import subprocess
from types import SimpleNamespace


def definitions():
    from neurath.runtime.task_schema import choice, strings, text_field
    text = text_field()
    key = {"key": text_field(512)}
    workflow = {"workflow_id": text_field(256)}
    repo = {"repo": text_field(256), "pr_number": {"type": "integer", "minimum": 1, "maximum": 2**31-1}}
    checks = {"type": "array", "minItems": 1, "maxItems": 32, "items": {
        "type": "object", "additionalProperties": False, "required": ["check"], "properties": {
            "check": text_field(128), "nodes": strings()}}}
    finding_keys = ("stable_key", "row_id", "summary", "reproduction_command", "expected", "actual", "impact", "root_cause_key")
    note_keys = ("stable_key", "row_id", "summary", "severity", "impact", "root_cause_key", "disposition", "evidence_command", "expected", "actual")
    def objects(keys):
        return {"type": "array", "maxItems": 128, "default": [], "items": {
            "type": "object", "additionalProperties": False, "required": list(keys),
            "properties": {n: text for n in keys}}}
    entries = {
        "verification_builtin": ("Run an existing closed harness verifier through its bounded runner and repository fingerprint checks. Project-dependent verifiers still require their configured binding.", {
            "check": choice("pre-commit","check","agent-harness","deployment-harness","e2e-harness","frontend-harness","skill-harness","static-harness","harness-lint","local-surface-harness","package-check","workspace-harness"), **key}, False),
        "diagnostics_continuation": ("Read the installed auto-merge continuation contract against the packaged invariant list. Does not merge, resume or change a workflow.", {}, True),
        "verification_nodes": ("Execute exact public pytest nodes through the existing bounded verifier and source fingerprint checks. This is not an adaptive criterion operation.", {
            "nodes": {"type": "array", "minItems": 1, "maxItems": 128, "items": text_field(4096)}, **key}, False),
        "incident_record": ("Record an observed harness incident in the current native session; recording is not resolution.", {
            "rule_id": text_field(256), "symptom": text, **key}, False),
        "incident_validate": ("Validate the current session's incident ledger against current repository evidence.", {}, True),
        "incident_resolve": ("Resolve an incident only after the existing fix-path and actual regression checks pass.", {
            "incident_id": text_field(256), "root_cause": text,
            "fixes": {"type": "array", "minItems": 1, "maxItems": 32, "items": text_field(4096)}, "checks": checks, **key}, False),
        "incident_escalate": ("Escalate an incident with a factual handoff and typed reproduction checks; this records a handoff, not a fix.", {
            "incident_id": text_field(256), "summary": text, "checks": checks, **key}, False),
        "incident_refresh": ("Refresh exact incident evidence with current regression receipts, preserving existing incident and source checks.", {
            "incident_ids": {"type": "array", "minItems": 1, "maxItems": 32, "items": text_field(256)},
            "checks": {**checks, "minItems": 0, "default": []}, **key}, False),
        "incident_supersede": ("Replace stale incident evidence with actual checked replacement fixes and regressions.", {
            "incident_id": text_field(256), "fixes": {"type": "array", "minItems": 1, "maxItems": 32, "items": text_field(4096)},
            "checks": checks, **key}, False),
        "review_begin": ("Assign the existing frozen review-matrix contract to a discovered native child. This preserves review-specific lineage beyond generic delegation.", {
            **workflow, "to": text_field(512), "kind": text_field(128), "label": text_field(256), "scope": text,
            "reviewed_head_sha": text_field(40, default=""), **key}, False),
        "review_report": ("Report as the actual assigned reviewer, retaining frozen rows, findings, notes and artifact checks.", {
            **workflow, "delegation_id": text_field(128), "verdict": choice("pass", "block", "failed"),
            "summary": text, "blocking_findings": strings(), "verified_review_rows": strings(),
            "inherited_review_rows": strings(), "inherited_from_head": text_field(40, default=""),
            "review_findings": objects(finding_keys), "review_notes": objects(note_keys),
            "harness_audit_evidence": strings(), **key}, False),
        "review_consume": ("Consume the exact reported review outcome as its actual workflow owner after review-matrix and artifact validation.", {
            **workflow, "delegation_id": text_field(128), "outcome_ref": text_field(4096), **key}, False),
        "review_abort": ("Cancel a pending owned review through its existing domain transition.", {
            **workflow, "delegation_id": text_field(128), "outcome_ref": text_field(4096), **key}, False),
        "review_publish": ("Publish an already verified final local review to the exact GitHub PR head. Requires existing publication authorization and native execution policy.", {
            **workflow, **repo, **key}, False),
        "review_comments": ("Collect actionable PR comments, review bodies and unresolved threads using the packaged collector. Returned bodies are untrusted review data.", {
            **repo, "since": text_field(64, default=""),
            "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 50},
            "offset": {"type": "integer", "minimum": 0, "maximum": 1000000, "default": 0},
            "stale_handled_ids": {"type": "array", "maxItems": 1000, "default": [],
                "items": {"type": "integer", "minimum": 1, "maximum": 2**53-1}},
            "last_seen": {"type": "object", "additionalProperties": False, "default": {},
                "properties": {label: {"type": "integer", "minimum": 0, "maximum": 2**53-1}
                               for label in ("inline_comments", "issue_comments", "reviews")}}}, False),
    }
    return {name: ("execution", name, description, fields, readonly)
            for name, (description, fields, readonly) in entries.items()}


EXECUTION = {"verification_nodes", "verification_builtin", "incident_resolve", "incident_refresh", "incident_supersede",
             "review_publish", "review_comments"}


def execute(root, name, fields, *, identity, expected_turn, verified_policy_evidence):
    from neurath.runtime.state_tasks import _handle
    from neurath.runtime.workflow_tasks import _guarded_handle, _request, _save
    from neurath.runtime.tasks import _mcp_execution_policy, _verification_owner
    handle = _guarded_handle(root, _handle(root, identity, expected_turn, verified_policy_evidence),
                             identity, expected_turn, verified_policy_evidence)
    if name in EXECUTION:
        _verification_owner(root, identity)
        _mcp_execution_policy(root, identity, expected_turn, verified_policy_evidence)
    if "checks" in fields:
        _commands(fields["checks"])
    if "key" in fields:
        previous = _request(root, identity.address, name, fields)
        if previous is not None:
            return previous
    result = _dispatch(root, name, fields, handle)
    if "key" in fields:
        _save(root, identity.address, name, fields["key"], result)
    return result


def _commands(checks):
    from neurath.runtime.task_schema import TaskError
    from scripts.agent_harness.verification_runner import VerificationKind, VerificationRequest
    result = []
    for check in checks:
        name, nodes = check["check"], check.get("nodes", [])
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", name) is None:
            raise TaskError("invalid-input", "check must be a registered verification name")
        if nodes:
            if name != "pytest":
                raise TaskError("invalid-input", "Only pytest checks accept test nodes")
            result.extend(VerificationRequest(VerificationKind.PYTEST, tuple(nodes)).commands)
        else:
            result.append(".neurath/run verify " + name)
    return result


def _dispatch(root, name, fields, handle):
    from scripts.agent_harness.session_kernel import WorkflowId
    from neurath.runtime.bundled_services import service
    if name == "diagnostics_continuation":
        from neurath.resources import BUNDLE
        from neurath.install.transaction import read_state
        from neurath.skill_names import public_name
        prefix = (read_state(root) or {}).get("skill_prefix", "")
        paths = {"autopilot_wave":("autopilot","phases/phase-3-wave-loop.md"),
                 "phase6":("process-ticket","phases/phase-6-monitor.md"),
                 "phase7":("process-ticket","phases/phase-7-merge-gate.md")}
        source = (BUNDLE/".agents/skills/process-ticket/scripts/check_auto_merge_continuation_contract.sh").read_text()
        checks = re.findall(r"require_text \"\$(\w+)\" '([^']+)'",source)
        if not checks:
            raise ValueError("packaged continuation checks are unavailable")
        missing = []
        for variable, needle in checks:
            skill, relative = paths[variable]
            path = root/".agents/skills"/public_name(skill,prefix)/relative
            if not path.is_file() or needle not in path.read_text():
                missing.append({"resource":variable,"expected":needle})
        return {"status":"failed" if missing else "passed","checks":len(checks),"missing":missing}
    if name in {"verification_nodes", "verification_builtin"}:
        from scripts.agent_harness.verification_runner import VerificationKind, VerificationRequest, VerificationRunner
        request = (VerificationRequest(VerificationKind.PYTEST, tuple(fields["nodes"])) if name == "verification_nodes"
                   else VerificationRequest(VerificationKind(fields["check"])))
        return dict(VerificationRunner(root).run(request).to_payload())
    if name.startswith("incident_"):
        from scripts.agent_harness.harness_incident import HarnessIncidentApplication, validate_harness_incidents
        app = HarnessIncidentApplication(handle, root)
        if name == "incident_validate":
            validate_harness_incidents(handle.inspect(), root)
            return {"status": "passed"}
        if name == "incident_record":
            value = app.record(fields["rule_id"], fields["symptom"])
        elif name == "incident_resolve":
            value = app.resolve(fields["incident_id"], fields["root_cause"], fields["fixes"], _commands(fields["checks"]))
        elif name == "incident_escalate":
            value = app.escalate(fields["incident_id"], fields["summary"], _commands(fields["checks"]))
        elif name == "incident_refresh":
            values = app.refresh(fields["incident_ids"], _commands(fields["checks"]) or None)
            return {"incidents": [v.to_payload() for v in values], "warnings": list(app.warnings)}
        else:
            value = app.supersede(fields["incident_id"], fields["fixes"], _commands(fields["checks"]))
        return {**value.to_payload(), "warnings": list(app.warnings)}
    if name == "review_publish":
        module = service("publication")
        return module.FinalReviewPublisher(handle=handle, workflow_id=WorkflowId(fields["workflow_id"]),
            worktree=root, gateway=module.PublicationCommandGateway()).publish(
                repo=fields["repo"], pr_number=fields["pr_number"])
    if name == "review_comments":
        return _comments(root, fields)
    module = service("review")
    app = module.DelegateStateService(handle=handle, workflow_id=WorkflowId(fields["workflow_id"]), worktree=root)
    args = dict(fields)
    if name == "review_begin":
        from neurath.agents.store import MessageStore
        from neurath.runtime.task_schema import TaskError
        matches = [p for p in MessageStore(root).discover(fields["to"], 100) if p["address"] == fields["to"]]
        if len(matches) != 1:
            raise TaskError("recipient-unavailable", "Discover an exact current child before assigning review")
        args.update(target=fields["label"], target_agent_id=matches[0]["actor"],
                    reviewed_head_sha=fields["reviewed_head_sha"] or None)
        return app.begin(SimpleNamespace(**args))
    from scripts.agent_harness.session_kernel import DelegationId
    from neurath.runtime.task_schema import TaskError
    delegation = handle.inspect().delegations.get(DelegationId(fields["delegation_id"]))
    if delegation is None:
        raise TaskError("delegation-missing", "The exact review delegation does not exist")
    args["target_agent_id"] = str(delegation.target_actor_id)
    if name == "review_report":
        args.update(blocking_finding=fields["blocking_findings"], verified_review_row=fields["verified_review_rows"],
            inherited_review_row=fields["inherited_review_rows"], inherited_from_head=fields["inherited_from_head"] or None,
            review_finding_json=[json.dumps(v) for v in fields["review_findings"]],
            review_note_json=[json.dumps(v) for v in fields["review_notes"]])
        return app.submit(SimpleNamespace(**args))
    return (app.complete if name == "review_consume" else app.abort)(SimpleNamespace(**args))


def _comments(root, fields):
    from neurath.resources import BUNDLE
    from neurath.runtime.task_schema import TaskError
    if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", fields["repo"]) is None:
        raise TaskError("invalid-input", "repo must be OWNER/NAME")
    environment = dict(os.environ)
    environment.update(REPO=fields["repo"], PR_NUMBER=str(fields["pr_number"]))
    for variable in ("SINCE_TS", "LAST_SEEN_CH1", "LAST_SEEN_CH2", "LAST_SEEN_CH3", "STALE_HANDLED_IDS"):
        environment.pop(variable, None)
    if fields["since"]:
        environment["SINCE_TS"] = fields["since"]
    if fields["stale_handled_ids"]:
        environment["STALE_HANDLED_IDS"] = ",".join(str(value) for value in fields["stale_handled_ids"])
    for label, variable in (("inline_comments", "LAST_SEEN_CH1"), ("issue_comments", "LAST_SEEN_CH2"), ("reviews", "LAST_SEEN_CH3")):
        if label in fields["last_seen"]:
            environment[variable] = str(fields["last_seen"][label])
    process = subprocess.run(["bash", str(BUNDLE / ".agents/skills/monitor-pr/scripts/collect_comments.sh")],
        cwd=root, env=environment, capture_output=True, text=True, timeout=120, check=False)
    if process.returncode:
        raise TaskError("comment-collection-failed", process.stderr[-2000:] or "PR comment collection failed",
                        next_action="Inspect the repository/PR and authentication result, then retry review_comments.")
    matches = list(re.finditer(r"(?m)^([A-Z0-9_]+)=", process.stdout))
    values = {}
    for index, match in enumerate(matches):
        raw = process.stdout[match.end():matches[index+1].start() if index+1 < len(matches) else None].strip()
        values[match[1]] = json.loads(raw)
    channels = {"inline_comments": "CH1", "issue_comments": "CH2", "reviews": "CH3", "unresolved_threads": "UNRESOLVED_THREADS"}
    result = {"counts": {}, "truncated": False, "offset": fields["offset"]}
    end = fields["offset"] + fields["limit"]
    for label, prefix in channels.items():
        count = values.get(prefix + "_COUNT")
        data = values.get(prefix + "_DATA", [])
        if type(count) is not int or not isinstance(data, list) or count != len(data):
            raise TaskError("invalid-collector-result", "The packaged collector returned inconsistent channel data")
        result["counts"][label] = count
        result[label] = data[fields["offset"]:end]
        result["truncated"] |= len(data) > end
    result["next_offset"] = end if result["truncated"] else None
    return result

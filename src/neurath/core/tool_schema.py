"""One closed MCP schema projection of core commands."""

from neurath.core.service import COMMANDS

STRING = {"type": "string", "minLength": 1}
STRINGS = {"type": "array", "items": STRING}
INTEGER = {"type": "integer", "minimum": 0}
FIELDS = {
    "check_name": STRING,
    "execution_id": STRING,
    "all_project": {"type": "boolean"},
    "publication_kind": {
        "enum": ["git-push", "pull-request", "pr-merge", "issue-closed", "release"]
    },
    "reference": STRING,
    "head": STRING,
    "asset_sha256": STRING,
    "run_id": STRING,
    "model": STRING,
    "message_id": STRING,
    "message_ids": STRINGS,
    "article_id": STRING,
    "include_read": {"type": "boolean"},
    "title": STRING,
    "create": {"type": "boolean"},
    "kind": {"enum": ["native_input", "user", "tool", "report"]},
    "summary": STRING,
    "query": {"type": "string"},
    "source_actor": STRING,
    "decisions": STRINGS,
    "next_steps": STRINGS,
    "lessons": STRINGS,
    "status": {"enum": ["active", "paused", "completed", "blocked"]},
    "action": STRING,
    "target": {"type": "object", "minProperties": 1},
    **{
        name: STRING
        for name in (
            "key",
            "task_id",
            "source_id",
            "goal",
            "skill",
            "phase_id",
            "digest",
            "reason",
            "body",
            "assignment_id",
            "checkout",
            "scope",
            "recipient",
            "provider",
            "_call_id",
        )
    },
    "subject": {"type": "string"},
    "expected_revision": {"type": "integer", "minimum": 1},
    "generation": {"type": "integer", "minimum": 1},
    "start": INTEGER,
    "end": INTEGER,
    "limit": {"type": "integer", "minimum": 1, "maximum": 16000},
    "source_ids": {**STRINGS, "minItems": 1},
    "dependencies": {**STRINGS, "uniqueItems": True},
    "changed_inputs": STRINGS,
    "passed": {"type": "boolean"},
    "execution": {"enum": ["subagent", "session", "cross-provider"]},
    "role": {"enum": ["worker", "reviewer", "executor"]},
    "verdict": {"enum": ["pass", "failed", "blocked", "cancelled"]},
    "outcomes": {"type": "object", "additionalProperties": STRINGS},
    "inputs": {"type": "object", "additionalProperties": {"type": "string"}},
    "acceptance": {
        "type": "array",
        "minItems": 1,
        "items": {
            "type": "object",
            "additionalProperties": False,
            "required": ["id"],
            "properties": {
                "id": STRING,
                "kinds": {
                    "type": "array",
                    "minItems": 1,
                    "uniqueItems": True,
                    "items": {
                        "enum": [
                            "report",
                            "check",
                            "review",
                            "publication",
                            "observation",
                            "approval",
                        ]
                    },
                },
                "subject_key": STRING,
                "operation": STRING,
                "expected_pass": {"type": "boolean"},
            },
        },
    },
}
DESCRIPTIONS = {
    "verification_prepare": "Prepare an exact registered project check for native execution. Run the returned action once; the owned subprocess retains the actual exit code. Use native waiting rather than polling unchanged state.",
    "task_list": "Read tasks owned by or assigned to this actual actor and its current input source. Use all_project only for an explicit project-wide inspection; other actors' work does not become your obligation.",
    "source_restore": "Restore exact original input text from an imported v1 prompt receipt for your retained Task. The original digest must match; this never upgrades provenance to human attestation or invents missing text.",
    "approval_record": "Record your interpretation of an actual user instruction for an exact action and target. Quote the retained original span. This is attributed semantic judgment, not native human attestation; peers and continuations cannot authorize new work. The target identifies the logical action being assessed; this record grants no native execution permission.",
    "session_status": "Read the native actor and its unfinished obligations. Reads require no writer lease.",
    "task_define": "Register an authorized user outcome with original source references and acceptance conditions.",
    "task_start": "Start the existing task using its current revision.",
    "skill_start": "Attach the installed skill and enforce its ordered phases on this task.",
    "phase_complete": "Complete only the current phase using retained evidence for every required condition.",
    "phase_restart": "Start rework of the same task at the skill-defined restart point; preserve previous attempts.",
    "task_complete": "Complete the user outcome only after all phases, assignments and acceptance conditions are satisfied.",
    "task_wait": "Record a blocker while preserving the unfinished task. Waiting does not permit normal completion.",
    "assignment_prepare": "Choose subagent, independent session or cross-provider execution based on the work; reserve its scope. Reviewer assignments require an explicit checkout whose observed source bytes remain the review target.",
    "assignment_report": "Return the actual assigned result; this settles the recipient report obligation, not the user task.",
    "assignment_accept": "Accept the observed report for its exact subject. Failed reports cannot be accepted as success.",
    "report_record": "Retain an attributed agent report. This cannot manufacture a tool observation or human approval.",
    "source_quote": "Return an exact source span and reject mismatched text digests.",
    "worktree_claim": "Acquire the writer lease for a checkout in this project. Identity does not change with its path.",
    "worktree_release": "Release your exact writer lease generation, independently of progress recording.",
}


def definitions():
    result = []
    for name, (required, optional, readonly) in COMMANDS.items():
        required = required | {"_call_id"} | (set() if readonly else {"key"})
        fields = required | optional | {"_call_id"}
        result.append(
            {
                "name": name,
                "description": DESCRIPTIONS.get(name, name.replace("_", " ").capitalize())
                + " Supply a fresh globally unique _call_id for this invocation. It only correlates the native hook observation; it does not identify or authorize an actor. Reuse the mutation key for idempotent retries, with a new _call_id.",
                "inputSchema": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": sorted(required),
                    "properties": {field: FIELDS[field] for field in sorted(fields)},
                },
                "annotations": {"readOnlyHint": readonly, "openWorldHint": False},
            }
        )
    return result

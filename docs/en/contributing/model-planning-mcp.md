<!-- updated: 2026-09-14; synced_from: 243400e58ca74c7fd79bcdd86b488953fa743b97 -->

# Choose a model against an observed assignment

[한국어](../../ko/contributing/model-planning-mcp.md) · [Contributor start](index.md)

A model plan records why a particular available model can carry out an authorized assignment under the intended execution settings. It makes that choice inspectable before a new native session does substantive work. It does not grade model quality or replace the agent's judgment about the task.

For the user's hypothetical saved-filter bug, an independent agent might only inspect API storage and responses, or it might need to trace API persistence and UI restoration together. Those assignments can have different difficulty and capability requirements. The plan must explain the actual question and constraints rather than select a model by a fixed name or presume that the most expensive option is necessary.

## Start with the destination's observed inventory

`provider_models(provider, worktree, refresh)` returns an inventory with an `inventory_id` for the target. `provider` is `codex` or `claude-code`; `worktree` scopes the destination and `refresh` requests a fresh observation. Model IDs, reasoning settings, capabilities, aliases, default-model provenance, context, price, and latency must come from actual adapter observations where available.

Unknown values remain unknown. An unknown price cannot satisfy a price ceiling as if it were zero. A reasoning mode absent from the observed model cannot be inferred from another model. Native aliases need source and revision provenance to resolve to a concrete model ID. An installed CLI and a remembered model catalog are insufficient substitutes for current inventory.

## Record the choice and what could invalidate it

`provider_plan` requires the provider, worktree, exact assignment, inventory reference, execution settings, selection, difficulty, confidence, rationale, and stable key. Supply nonempty `evidence` and `replan_triggers` as well: the planning contract requires them even though their schema has empty defaults. `assignment_revision` begins at 1.

The fields serve distinct purposes:

| Field | Decision it records |
| --- | --- |
| `selection.model` | An observed model ID/verified alias, or the literal `"inherit"` for the destination's observed default. |
| `selection.reasoning` | An observed reasoning setting supported by that model, when explicitly chosen. |
| `execution` | The requested policy route: mode, approval policy/reviewer, collaboration mode, Claude permission mode, and optional project metadata. |
| `difficulty` | `routine`, `standard`, or `complex`, based on this assignment. |
| `confidence` | `low`, `medium`, or `high` confidence in the plan. |
| `evidence` and `rationale` | Concrete assignment/inventory observations and the reasoning for this choice. |
| `rejected_alternatives` | Alternatives considered and why they were not selected. |
| `replan_triggers` | Changes that require reconsideration, such as scope, capability, or policy changes. |
| `constraints` | Hard provider, model, capability, context, price, and latency requirements. |

`constraints` supports `explicit_model`, `allowed_providers`, `required_capabilities`, `min_context_tokens`, `max_input_price_per_million`, and `max_latency_ms`. A supplied hard requirement must be established by observations. Missing capability, unknown constrained price, unsupported reasoning, or a provider mismatch rejects creation of a usable plan.

A minimal *shape* for inheritance is shown below. Replace every placeholder with current values and preserve the assignment unchanged at dispatch.

```json
{
  "provider": "codex",
  "worktree": "<authorized absolute worktree>",
  "assignment": "Investigate API storage and responses for the saved filter; return persistence and response evidence.",
  "assignment_revision": 1,
  "inventory_id": "<returned inventory id>",
  "execution": {"mode": "inherit"},
  "selection": {"model": "inherit"},
  "difficulty": "standard",
  "evidence": ["<actual scope and inventory observations>"],
  "confidence": "medium",
  "rationale": "<why this observed default fits the bounded investigation>",
  "replan_triggers": ["The assignment expands from diagnosis to implementation."],
  "key": "saved-filter-model-plan-1"
}
```

## Keep the two meanings of inheritance separate

`selection.model="inherit"` chooses the target's observed default model. `execution.mode="inherit"` preserves the immediate creator's supported native execution policy. `execution.mode="target-native"` uses explicitly authorized destination settings. None of these choices adopts another session's unfinished work or establishes app project membership.

If the default model cannot yet be resolved, the system can permit `preparation-only` for the same authorized session when that preparation does not violate hard constraints. A constrained unknown default or an unsupported explicit reasoning setting cannot be guessed into validity. Substantive work waits for actual model/default readback. Do not create an unrelated discovery session to evade this boundary.

Before saving an inherited-policy plan, the runtime applies the same permission mapping used at execution. Unsupported hook/tool controls or conflicting requested modes reject the proposal before it can become ready. Existing target configuration observations remain read-only; planning does not dispatch a model job. Explicit `target-native` remains a separate choice, never an automatic fallback after failed inheritance.

## Preserve revisions through dispatch and change

The returned plan includes its identity and revision, the resolved model or preparation-only state, and binding to the assignment, inventory facts, policy, owner, and target. `provider_plan_read(plan_id, plan_revision)` retrieves that exact version. Pass the returned reference to `provider_run`; use actual returned revisions instead of assuming every plan is still revision 1.

To update a plan, provide `plan_id`, the current `expected_revision`, a new stable request key, and the complete revised proposal. Compare-and-swap rejects stale writers. Repeating an identical accepted request with its original key is durable and idempotent; a failed proposal does not consume its request key.

Assignment, provider/host target, policy, constraints, or relevant model facts can invalidate the plan. Inventory refresh alone is not expiry: changed facts that affect selection are what matter. An explicit model choice need not become stale because an unrelated default changed. At session creation, actual model readback must match the resolved plan or verified alias; otherwise the substantive assignment is not admitted as successful creation.

## Diagnose a rejected plan without weakening its requirements

If inventory is missing, obtain the target observation. If a hard requirement is unverified, obtain evidence or return to the authorized requirement decision. If the plan is stale, read current state and create a revision that describes the current assignment. If the created native session has a policy/model mismatch, retain that mismatch and do not submit the assignment under an invented success state.

Model choice does not authorize a more permissive execution mode, additional sessions, app actions, or worktree takeover. The returned tool error envelope supplies `code`, `message`, `state`, `retryable`, and `next_action`. Read the precise prerequisite instead of treating any rejection as a reason to retry with fewer constraints.

## Source and tests

[src/neurath/providers/model_inventory.py](../../../src/neurath/providers/model_inventory.py) collects observations; `model_planning.py` validates and persists plans; [src/neurath/runtime/model_tasks.py](../../../src/neurath/runtime/model_tasks.py) exposes the named tools. Execution binds them through [src/neurath/providers/execution_plan.py](../../../src/neurath/providers/execution_plan.py).

[tests/test_model_planning.py](../../../tests/test_model_planning.py) covers owner fencing, durable replay, revisions, stale bindings, unknown constrained values, unresolved defaults, and alias/default provenance. These tests validate the plan contract. They do not establish a universal model ranking or prove that a particular model solves the user's filter bug.
## Named input reference

The tables below are the current named-tool input contract. Nested required fields are required when their parent object or array item is supplied. Schema acceptance is only the first check; native identity, ownership, source, revision, and operation-specific prerequisites still apply. The host supplies `_neurath_binding`; do not synthesize it.

Every response has `ok` and `operation`. A successful call carries its canonical `result`; a failure carries `error.code`, `error.message`, `error.state`, `error.retryable`, and `error.next_action`. An `ok` envelope establishes the stated operation only, not the user goal. Preserve returned IDs and revisions for dependent calls.

### `provider_models`

| Field | Presence / default | Type and limits |
| --- | --- | --- |
| `provider` | required | text: `"codex"`, `"claude-code"` |
| `worktree` | optional; default `""` | text; 0–4096 characters |
| `refresh` | optional; default `false` | boolean |

### `provider_plan`

| Field | Presence / default | Type and limits |
| --- | --- | --- |
| `provider` | required | text: `"codex"`, `"claude-code"` |
| `worktree` | required | text; 1–4096 characters |
| `assignment` | required | text; 1–16000 characters |
| `assignment_revision` | optional; default `1` | integer; 1–2147483647 |
| `inventory_id` | required | text; 1–128 characters |
| `execution` | required | object; declared fields only |
| `execution.mode` | optional | text: `"inherit"`, `"target-native"`, `"read-only"`, `"workspace-write"`, `"danger-full-access"`, `"native"` |
| `execution.approval_policy` | optional | text: `"never"`, `"on-request"`, `"untrusted"` |
| `execution.approvals_reviewer` | optional | text: `"user"`, `"auto_review"` |
| `execution.collaboration_mode` | optional | text: `"default"`, `"plan"` |
| `execution.permission_mode` | optional | text: `"plan"`, `"dontAsk"`, `"default"`, `"acceptEdits"`, `"bypassPermissions"`, `"auto"` |
| `execution.project_id` | optional | text; 1–256 characters |
| `selection` | required | object; declared fields only |
| `selection.model` | required | text; 1–256 characters |
| `selection.reasoning` | optional | text; 1–100 characters |
| `constraints` | optional; default `{}` | object; declared fields only |
| `constraints.explicit_model` | optional | text; 1–256 characters |
| `constraints.allowed_providers` | optional; default `[]` | array; 0–32 items; text; 1–16000 characters |
| `constraints.required_capabilities` | optional; default `[]` | array; 0–32 items; text; 1–16000 characters |
| `constraints.min_context_tokens` | optional | integer; 0–∞ |
| `constraints.max_input_price_per_million` | optional | number; 0–∞ |
| `constraints.max_latency_ms` | optional | number; 0–∞ |
| `difficulty` | required | text: `"routine"`, `"standard"`, `"complex"` |
| `evidence` | optional; default `[]` | array; 1–32 items; text; 1–16000 characters |
| `confidence` | required | text: `"low"`, `"medium"`, `"high"` |
| `rationale` | required | text; 1–16000 characters |
| `rejected_alternatives` | optional; default `[]` | array; 0–32 items; text; 1–16000 characters |
| `replan_triggers` | optional; default `[]` | array; 1–32 items; text; 1–16000 characters |
| `key` | required | text; 1–512 characters |
| `plan_id` | optional; default `""` | text; 0–128 characters |
| `expected_revision` | optional; default `0` | integer; 0–2147483647 |

### `provider_plan_read`

| Field | Presence / default | Type and limits |
| --- | --- | --- |
| `plan_id` | required | text; 1–128 characters |
| `plan_revision` | optional; default `1` | integer; 1–2147483647 |

<!-- date: 2026-09-14; synced_from: 655c8768709e59b5e5012bab0adc4d888e3e7fa5 + current working-tree facts -->

[한국어](../../ko/contributing/model-planning-mcp.md)

# Bind an observed model choice to one assignment

Model planning records why a particular observed model is sufficient for authorized independent work, then binds that choice to the actual provider execution. It preserves user constraints and prevents a changed assignment, stale policy, or different created model from silently reusing an old decision. It does not authorize creating a session.

## Decide whether a provider run is needed

Use native leaf children for bounded work within the current task when their supported topology is enough. An independent lifetime, cross-provider work, or required isolation can justify an owned provider session. Record the reason before planning one. A peer message, a model recommendation, or an available catalog is not creation authority.

Assess the role using ambiguity, change breadth, reasoning depth, failure impact, required tools/modalities/context, and the strength of available verification. `difficulty` is `routine`, `standard`, or `complex`; `confidence` is `low`, `medium`, or `high`. These are reasoned judgments with evidence, not a rigid point score or token-count gate.

| Example assignment | Assessment to record | Selection consequence |
| --- | --- | --- |
| Mechanically compare an explicit field list against tests | Narrow scope, little ambiguity, direct check | Smallest observed model meeting the constraints |
| Resolve a lifecycle race across ownership and recovery | Multiple state transitions, uncertain effects, failure impact | A model supported by evidence of the required capabilities |
| Use a specific provider/model requested by the user | Fixed constraint regardless of preferred ranking | Use that exact observed model or report why unavailable |
| Stay below an explicit cost or latency limit | Requires observed values for the constrained dimension | Unknown values cannot establish compliance |

There is no fixed model ranking or hardcoded price table. Unknown capability, cost, or latency remains unknown. Planning does not buy quota, silently substitute a provider, or authorize a new data destination.

## Observe inventory once, reuse it deliberately

`provider_models` requires `provider` (`codex` or `claude-code`); `worktree` is optional and `refresh` defaults to `false`.

```json
{"provider":"codex","worktree":"/absolute/path/to/authorized-worktree","refresh":false}
```

The result records an inventory identity, models, source, and observation revision. Reuse the observation for the native issuer/provider session across turns and worktrees. A new assignment may need a new plan without needing another catalog query. Refresh only after an explicit user request or concrete evidence invalidating the observation.

Codex uses its native adapter. Claude uses a short official SDK metadata handshake without a model query, retaining applicable settings and removing the parent identity environment. Catalog availability does not itself prove authentication, successful inference, or the actual configured default.

## Prepare the exact plan

`provider_plan` requires provider, target worktree, assignment, inventory ID, execution object, selection, difficulty, confidence, rationale, and stable key. Provide nonempty `evidence` and `replan_triggers` as well: their default empty arrays do not satisfy the domain contract. Each list supports at most 32 items. The assignment is limited to 16,000 characters and revisions are positive integers.

Example input below is structurally valid after replacing the three illustrative target/inventory/model values with actual authorized and observed values. `evidence` describes observations that must actually have been made.

```json
{
  "provider":"codex",
  "worktree":"/absolute/path/to/authorized-worktree",
  "assignment":"Compare the documented response fields with the current API tests; report discrepancies without editing.",
  "assignment_revision":1,
  "inventory_id":"RETURNED_INVENTORY_ID",
  "execution":{"mode":"inherit"},
  "selection":{"model":"OBSERVED_MODEL_ID"},
  "constraints":{"allowed_providers":["codex"]},
  "difficulty":"routine",
  "evidence":["The assignment names a bounded field comparison and direct test evidence."],
  "confidence":"high",
  "rationale":"The observed model supports the tools and context required for this bounded comparison.",
  "rejected_alternatives":["A larger model has no evidenced benefit for this assignment."],
  "replan_triggers":["The assignment expands to implementation or the observed model becomes unavailable."],
  "key":"response-contract-plan-1"
}
```

The execution object can carry `mode`, approval fields, collaboration mode, Claude permission mode, and optional project ID as supported by the actual route. The selection object accepts `model` and optional `reasoning`. Constraints may include `explicit_model`, `allowed_providers`, `required_capabilities`, `min_context_tokens`, `max_input_price_per_million`, and `max_latency_ms`. A reasoning setting must be supported by the observed model; omitted reasoning is not an instruction to invent one.

The saved result binds the assignment digest and revision, issuer/provider, effective policy digest and mapping revision, inventory observation, choice, rationale, constraints, and rejected alternatives. It returns `plan_id`, `revision`, a selection status, and `resolved_model_id`; default provenance is retained when relevant. `provider_plan_read` reads a specific `plan_id` and `plan_revision`.

To revise a plan, provide its `plan_id`, the actual latest `expected_revision`, and a new stable request key. The same key with changed input conflicts. Revisions remain attributable instead of mutating an earlier decision in place.

## Keep model inheritance separate from permissions

`execution.mode="inherit"` and `provider_run.mode="inherit"` concern execution policy. They do not select a model. Current model selection represents the inherited-model sentinel as `selection.model="inherit"`; there is no `selection.mode` field in the public schema.

For model inheritance, the target provider's observed configured default is the subject. It is not the cross-provider parent's model or a catalog recommendation. A resolved default requires `default_source` and `default_observation_revision` alongside `resolved_model_id`. Without a resolved default, a plan can be `preparation-only` only when it has no hard model/capability/context/price/latency constraints or reasoning selection that require proof. Substantive validation requires a ready plan.

Preparation may observe the default on the same already-authorized session and produce a new plan revision before the assignment. It must not create an extra discovery session. If the user constrains paid calls and the required observation cannot satisfy that constraint, retain the gap. Permission inheritance is separately bounded by [the transport policy contract](provider-transports.md); neither form of inheritance implies every provider-native setting has been copied.

## Choose target-native execution explicitly

When the user wants each provider to retain its own native settings, set `execution.mode="target-native"` in `provider_plan` and `mode="target-native"` in `provider_run`. The plan revision and assignment must match, just as in the inheritance example. Model selection remains separate: it can name an observed model or use `selection.model="inherit"` for the target's observed configured default.

The target's effective defaults must be observed and supported. Do not add conflicting explicit approval, reviewer, collaboration, or permission settings, copy the source's configuration, or switch strategies merely because `inherit` failed. [Provider transports](provider-transports.md) describes this policy boundary; [continuity](provider-continuity.md) covers taking over existing work rather than creating an independent assignment.

## Admit and verify the actual execution

Call `provider_run` with the exact plan ID and returned revision, the unchanged assignment and assignment revision, and a stable key. For the plan above, the binding has this shape:

```json
{
  "provider":"codex",
  "worktree":"/absolute/path/to/authorized-worktree",
  "assignment":"Compare the documented response fields with the current API tests; report discrepancies without editing.",
  "assignment_revision":1,
  "model":"OBSERVED_MODEL_ID",
  "mode":"inherit",
  "plan_id":"RETURNED_PLAN_ID",
  "plan_revision":1,
  "key":"response-contract-run-1"
}
```

Use the actual returned revision rather than assuming `1` outside this new-plan example. Validation happens before durable admission. After native creation, the actual model is checked before substantive assignment; a missing model or mismatch blocks work while retaining diagnostic native identity. Alias equivalence requires an authoritative mapping rather than similarity of names.

The shared tool result envelope contains `ok` and `operation`, plus `result` on success or an error containing `code`, `message`, `state`, `retryable`, and `next_action`. Read the structured outcome. A valid plan or accepted run does not prove the requested effects occurred.

## Replan only for a material change

| Condition | Required response |
| --- | --- |
| Assignment, target, provider, constraints, or effective policy changed | New plan revision bound to the current context |
| Policy mapping revision or observed default changed | Refresh the invalidated observation as needed, then replan |
| Inventory has concrete invalidating evidence | Observe current catalog and revalidate selection |
| Elapsed time or an ordinary message only | Retain the selection; time alone does not expire it |
| Create response is uncertain | Reconcile the existing request/key/plan before another attempt |
| A different model is now needed | New plan revision plus reconciliation of the already-authorized attempt |
| Created model differs or is missing | Block substantive assignment and inspect retained native diagnostics |

Resume and normal messages preserve the selection; ending a turn is not a reason to restart or switch models. An uncertain create must not become two independent sessions. `provider_status` is diagnostic after relevant events or errors, and recovery uses the recorded owned session as described in [provider transports](provider-transports.md).

## Verify planning and named-tool behavior

[Model planning](../../../src/neurath/providers/model_planning.py) implements typed observations, selection validation, immutable revisions, and staleness. [Task schemas](../../../src/neurath/runtime/task_schema.py), [provider execution](../../../src/neurath/runtime/provider_execution.py), and [the MCP server](../../../src/neurath/agents/mcp.py) carry the named interfaces. Deterministic checks validate structure, constraints, and bindings; they do not certify the subjective difficulty assessment or final task quality.

[Model-planning tests](../../../tests/test_model_planning.py), [provider-job tests](../../../tests/test_provider_jobs.py), and [MCP guidance tests](../../../tests/test_mcp_guidance.py) cover the corresponding contracts. Acceptance includes fixed or unavailable models, unknown constrained properties, unsupported reasoning, changed plans, alias/mismatch checks, and uncertainty after admission. Installed policies, skills, notifications, and error `next_action` must lead callers through named tools. Recall, peer messages, newsroom, and status should use those named operations; normal editing and tests remain native host work.

An unavailable MCP or unsupported mode is an explicit limitation, not permission to route routine work through an arbitrary CLI or `agent(argv)` gateway. Source tests, installed guidance, and real native model/tool-choice observations are separate evidence in [validation](validation.md).

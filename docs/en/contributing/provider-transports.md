<!-- updated: 2026-09-14; synced_from: 243400e58ca74c7fd79bcdd86b488953fa743b97 -->

# Run work in another native session

[한국어](../../ko/contributing/provider-transports.md) · [Contributor start](index.md)

A provider is the host through which an agent executes: currently Codex or Claude Code. A transport is the connection used to create or communicate with that host's session. Neurath uses these connections when authorized work needs an independent root with its own native identity, settings, activation, and checkout ownership.

For the hypothetical saved-filter defect, a second root could independently inspect API storage and responses while the first investigates reload restoration. An existing peer may already have the answer, and a direct native child may be sufficient for a bounded investigation. Choose the relationship first using [the collaboration contract](collaboration-contract.md); creating an independent session is a distinct action.

## From an available route to actual execution

`provider_capabilities(provider)` lists implemented routes and the conditions for their use. Current host tools and live connections determine availability. A binary version, an installed desktop app, or a capability row cannot prove that a usable session exists.

| Route | Implemented scope | Required observation |
| --- | --- | --- |
| Codex app-server | Create, discover, connect, message, status, resume, cancel | An explicit connected JSON-RPC transport, owned session, applied policy readback. |
| Codex app tools | Create, discover, read/connect, message, status, peer message | The relevant app tool in the current host inventory; app creation policy is not attested by this catalog. |
| Claude Agent SDK | Create, message, status, cancel | An owned streaming client, explicit native permission mode, and hook readiness. OS confinement is a separate observation. |
| Claude native tools | Discover and message peers | The current native tools and an exact discovered recipient. |
| Claude background inventory | Discover and status | Native background-job observations; short job IDs are distinct from native session UUIDs. Policy remains separately observed. |
| CLI | Create, status, resume, cancel for owned bounded runs | Installed authenticated CLI; this is not live attachment to arbitrary sessions. |
| Claude Desktop | No external session-control operation in this adapter | Desktop installation alone supplies no route. |

`provider_route` selects a proposed operation or reports a precise missing prerequisite. Its operations are `create`, `discover`, `connect`, `status`, `message`, `resume`, `cancel`, and `peer`. A route response has not created a session, changed a policy, or submitted the assignment.

## Bind model choice and execution settings before dispatch

Read `provider_models`, save a revisioned `provider_plan`, and pass its exact `plan_id` and `plan_revision` to `provider_run`. The assignment and `assignment_revision` must match the plan. The [model planning reference](model-planning-mcp.md) explains inventory provenance, hard constraints, and unresolved defaults.

Model inheritance uses `selection.model="inherit"`. Execution inheritance uses `execution.mode="inherit"` in the plan and `mode="inherit"` at dispatch. These are different dimensions. Execution inheritance preserves the immediate creator's currently observed native policy. Explicit settings supplied alongside it are equality requirements: they cannot quietly widen or narrow permissions. Cross-provider mapping must preserve observed filesystem, network, tool, and hook restrictions; unsupported equivalence blocks the request. Claude `dontAsk` must not become `bypassPermissions`.

An explicitly authorized `target-native` mode uses the destination's existing defaults, hooks, and tool rules. It does not copy source credentials or rewrite target settings. Conflicting requested overrides are rejected, and failed inheritance is not permission to switch modes silently. Choosing destination settings does not settle model selection, prove permission equivalence, confer app affiliation, or adopt unfinished tasks.

## Read admission as the start of supervision

A planned call has this shape. Angle-bracket values stand for exact observations or returned references and must be replaced before invocation.

```json
{
  "provider": "codex",
  "worktree": "<authorized absolute worktree>",
  "assignment": "<the exact planned API investigation>",
  "assignment_revision": 1,
  "mode": "inherit",
  "plan_id": "<returned plan id>",
  "plan_revision": 1,
  "key": "saved-filter-api-run-1"
}
```

`provider_run` returns a durable `run_id` promptly. Admission means supervision was recorded, not that the assignment completed. Before target editing, the system must verify installation, native activation, effective policy, actual selected model, claim, and necessary tools. If created-session readback disagrees with the requested model or policy, the assignment must not be submitted as though creation succeeded.

Normal provider work has no total task lifetime deadline. Request, connection, and write timeouts bound their own transport operations. Durable lifecycle and result messages carry progress and completion. Use `provider_status(run_id)` after a reported event or transport failure for diagnosis; do not repeatedly poll it as a completion mechanism.

## Interpret Claude results in their actual order

A Claude `ResultMessage` is a result container, not a success assertion. The adapter evaluates it in this order:

1. An interruption or cancellation reason yields `cancelled`.
2. Otherwise, `deferred_tool_use` yields `waiting`, including when historical `permission_denials` are present.
3. Otherwise, `is_error` or permission denials yield `failed`.
4. Otherwise, the result is `completed`.

A waiting result reports `approval_pending`. Cancellation overrides pending approval. Preserve this precedence when changing the SDK adapter; treating every denial as terminal would incorrectly fail a currently deferred approval, while treating every result as success would lose real failures.

Completion still needs the authenticated result to reach the original participant, its full body to be read and acknowledged, and the owner's task outcome to be recorded. A report that the API investigation is complete does not alone prove the entire filter defect is fixed. The original acceptance conditions remain the integration target.

## Cancellation, recovery, and app-created work

`provider_cancel(run_id)` requests cancellation through the owned run's private event channel. The terminal message confirms the outcome; admission does not prove that the process stopped. It is not an arbitrary PID signal operation.

`provider_recover(run_id, key)` restores the issuer's recorded execution only after verified native process and connection closure. It preserves the original run and does not rerun the original goal or resume a foreign live session. On uncertain admission, retain the same key and request rather than create duplicate work. To move unfinished ownership into a different root, use [receiver-led continuity](provider-continuity.md).

App-created roots have a separate route. When the user requests an app-associated task, pair the actual `create_thread` or `send_message_to_thread` delivery with its completion and matching native turn. Recognized context kinds `plugins.recommendations`, `agents_md.instructions`, and `environments.environment_context` may accompany that delivery. Unknown context, mismatched turns, missing completion, or conflicting human input prevent reconciliation. Such delivery can activate a native turn without creating a new user-prompt receipt or fresh approval. Local `app_project` diagnostics and native execution metadata must remain separate observations; see [agent roles](agents-reference.md).

## Source and regression checks

The route catalog is [src/neurath/providers/catalog.py](../../../src/neurath/providers/catalog.py); policy mapping is in [src/neurath/runtime/provider_policy.py](../../../src/neurath/runtime/provider_policy.py) and [src/neurath/providers/permission_inheritance.py](../../../src/neurath/providers/permission_inheritance.py). Execution and supervision are in [src/neurath/providers/execution.py](../../../src/neurath/providers/execution.py), `execution_claude.py`, `jobs.py`, `supervision.py`, and `job_recovery.py`.

Relevant tests include [tests/test_provider_task_run.py](../../../tests/test_provider_task_run.py), [tests/test_provider_policy_bridge.py](../../../tests/test_provider_policy_bridge.py), [tests/test_target_native_policy.py](../../../tests/test_target_native_policy.py), [tests/test_provider_jobs.py](../../../tests/test_provider_jobs.py), and [tests/test_provider_reply_route.py](../../../tests/test_provider_reply_route.py). Source and adapter tests establish their individual contracts; report actual native activation, permissions, results, and app observations separately when validating a live installation.
## Named input reference

The tables below are the current named-tool input contract. Nested required fields are required when their parent object or array item is supplied. Schema acceptance is only the first check; native identity, ownership, source, revision, and operation-specific prerequisites still apply. The host supplies `_neurath_binding`; do not synthesize it.

Every response has `ok` and `operation`. A successful call carries its canonical `result`; a failure carries `error.code`, `error.message`, `error.state`, `error.retryable`, and `error.next_action`. An `ok` envelope establishes the stated operation only, not the user goal. Preserve returned IDs and revisions for dependent calls.

### `provider_capabilities`

| Field | Presence / default | Type and limits |
| --- | --- | --- |
| `provider` | required | text: `"codex"`, `"claude-code"` |

### `provider_route`

| Field | Presence / default | Type and limits |
| --- | --- | --- |
| `provider` | required | text: `"codex"`, `"claude-code"` |
| `operation` | required | text: `"create"`, `"discover"`, `"connect"`, `"status"`, `"message"`, `"resume"`, `"cancel"`, `"peer"` |
| `native_session` | optional; default `""` | text; 0–256 characters |
| `model` | optional; default `""` | text; 0–256 characters |
| `project_id` | optional; default `""` | text; 0–256 characters |
| `message_id` | optional; default `""` | text; 0–256 characters |
| `worktree` | optional; default `""` | text; 0–4096 characters |
| `assignment` | optional; default `""` | text; 0–16000 characters |
| `plan_id` | optional; default `""` | text; 0–128 characters |
| `plan_revision` | optional; default `1` | integer; 1–2147483647 |
| `assignment_revision` | optional; default `1` | integer; 1–2147483647 |
| `reasoning_effort` | optional; default `""` | text; 0–100 characters |
| `requested` | optional; default `{}` | object; declared fields only |
| `requested.sandbox` | optional | text: `"read-only"`, `"workspace-write"`, `"danger-full-access"`, `"native"` |
| `requested.permission_mode` | optional | text: `"plan"`, `"dontAsk"`, `"default"`, `"acceptEdits"`, `"bypassPermissions"`, `"auto"` |
| `requested.approval_policy` | optional | text: `"never"`, `"on-request"`, `"untrusted"` |
| `requested.approvals_reviewer` | optional | text: `"user"`, `"auto_review"` |
| `requested.collaboration_mode` | optional | text: `"default"`, `"plan"` |

### `provider_run`

| Field | Presence / default | Type and limits |
| --- | --- | --- |
| `worktree` | required | text; 1–4096 characters |
| `assignment` | required | text; 1–16000 characters |
| `model` | optional; default `""` | text; 0–256 characters |
| `project_id` | optional; default `""` | text; 0–256 characters |
| `provider` | optional; default `"codex"` | text: `"codex"`, `"claude-code"` |
| `mode` | optional; default `"inherit"` | text: `"inherit"`, `"target-native"`, `"read-only"`, `"workspace-write"`, `"danger-full-access"`, `"native"` |
| `permission_mode` | optional; default `""` | text: `""`, `"plan"`, `"dontAsk"`, `"default"`, `"acceptEdits"`, `"bypassPermissions"`, `"auto"` |
| `approval_policy` | optional; default `""` | text: `""`, `"never"`, `"on-request"`, `"untrusted"` |
| `approvals_reviewer` | optional; default `""` | text: `""`, `"user"`, `"auto_review"` |
| `collaboration_mode` | optional; default `""` | text: `""`, `"default"`, `"plan"` |
| `plan_id` | optional; default `""` | text; 0–128 characters |
| `plan_revision` | optional; default `1` | integer; 1–2147483647 |
| `assignment_revision` | optional; default `1` | integer; 1–2147483647 |
| `reasoning_effort` | optional; default `""` | text; 0–100 characters |
| `key` | optional; default `""` | text; 0–512 characters |

### `provider_status`

| Field | Presence / default | Type and limits |
| --- | --- | --- |
| `run_id` | required | text; 1–128 characters |

### `provider_cancel`

| Field | Presence / default | Type and limits |
| --- | --- | --- |
| `run_id` | required | text; 1–128 characters |

### `provider_recover`

| Field | Presence / default | Type and limits |
| --- | --- | --- |
| `run_id` | required | text; 1–128 characters |
| `key` | required | text; 1–512 characters |

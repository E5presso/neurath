# Shared task execution

<!-- date: 2026-09-09; synced_from: baseline f69cb6402683bb2e0bfe56ed04c63f808b263f06 plus current working-tree stdio MCP changes; scope: source, not live-host certification -->

**English** · [한국어](../../ko/contributing/task-tools.md)

[Contributing](index.md) · [Architecture](architecture.md) · [Provider transports](provider-transports.md)

The current source registers **132 named tasks** in `runtime/task_schema.py` and its domain modules.
Registration is not proof that an existing host has reloaded every tool or that all paths have
passed installed-host acceptance. [Model planning and MCP operation](model-planning-mcp.md) and
[Provider collaboration](collaboration-contract.md) define the required behavior.

Named MCP tools are the agent-facing interface. `runtime/tasks.py` dispatches their structured
input to existing stores and kernel services without requiring an agent to assemble CLI argv.
CLI compatibility remains for saved callers and internal execution. It is
not the normal workflow, and an arbitrary `agent(argv)` gateway does not count as migration.

## Registered source surface

This inventory groups the exact registered names. Read each exposed input schema before calling;
not every operation in a group has the same input or authority.

| Function | Actual named tools |
| --- | --- |
| Session readiness | `session_status` |
| Independent execution | `provider_cancel`, `provider_recover`, `provider_run`, `provider_status` |
| Provider discovery | `provider_capabilities`, `provider_route` |
| Memory | `memory_checkpoint`, `memory_recall` |
| Project checks | `verification_run` |
| Peer communication | `collaboration_ack`, `collaboration_close`, `collaboration_conversation`, `collaboration_discover`, `collaboration_forward`, `collaboration_inbox`, `collaboration_message`, `collaboration_publish`, `collaboration_register`, `collaboration_reply`, `collaboration_send`, `collaboration_submitted`, `collaboration_subscribe`, `collaboration_unsubscribe` |
| Assigned task lifecycle | `collaboration_accept`, `collaboration_assign`, `collaboration_report`, `collaboration_task` |
| Newsroom | `newsroom_comment`, `newsroom_headlines`, `newsroom_peers`, `newsroom_publish`, `newsroom_read`, `newsroom_revise`, `newsroom_seen` |
| State, artifacts and ownership | `artifact_put`, `artifact_read`, `material_abandon`, `material_prepare`, `material_read`, `material_resolve`, `session_inspect`, `turn_inspect`, `worktree_claim`, `worktree_inspect`, `worktree_release` |
| Learning, releases and reporting | `learning_defer`, `learning_history`, `learning_pending`, `learning_status`, `maintenance_choice_prepare`, `maintenance_choice_read`, `releases_apply`, `releases_check`, `releases_choose`, `releases_notice`, `releases_prepare`, `releases_recover`, `releases_status`, `reporting_approve`, `reporting_consent`, `reporting_list`, `reporting_prepare`, `reporting_read`, `reporting_reconcile`, `reporting_status`, `reporting_submit` |
| Model planning | `provider_models`, `provider_plan`, `provider_plan_read` |
| Phases and evaluation | `adaptive_override_goal`, `adaptive_preflight`, `adaptive_read`, `adaptive_replace`, `delegation_assign`, `delegation_prepare`, `evaluation_consume`, `evaluation_execute`, `evaluation_prepare`, `evaluation_read`, `evaluation_report`, `phase_complete`, `phase_current`, `phase_evidence_prepare`, `phase_finalize`, `phase_start`, `workflow_advance`, `workflow_finalize`, `workflow_start` |
| Context, enclave and evaluation loops | `diagnostics_integrity`, `diagnostics_profile`, `diagnostics_project`, `enclave_delete`, `enclave_read`, `enclave_set`, `evaluation_loop_close`, `evaluation_loop_open`, `evaluation_loop_read`, `evaluation_loop_round`, `turn_yield` |
| Verification, incidents and reviews | `diagnostics_continuation`, `incident_escalate`, `incident_record`, `incident_refresh`, `incident_resolve`, `incident_supersede`, `incident_validate`, `review_abort`, `review_begin`, `review_comments`, `review_consume`, `review_publish`, `review_report`, `verification_builtin`, `verification_nodes` |
| Installation administration | `installation_apply`, `installation_plan`, `installation_recover` |
| Process evidence and cleanup | `process_evidence_record`, `worktree_cleanup`, `worktree_isolation` |
| PR monitoring | `monitor_ack`, `monitor_cancel`, `monitor_event`, `monitor_external_wait`, `monitor_handoff`, `monitor_readback`, `monitor_recover`, `monitor_start`, `monitor_status` |
| Delivery recovery | `delivery_redrive`, `delivery_status` |

## Inputs and authority

Responses use `ok`, `operation` and the canonical `result`, or a structured `error` containing
code/message/state/retryable/next_action. A failed check retains its result. A checkpoint remains
an agent report. Successful state bookkeeping does not establish independent review or product completion.

The native hook binds actor, session, foreground turn, worktree, input and tool invocation.
Resource references identify targets; they do not let a caller supply its own identity. Changed,
expired or closed invocation bindings cannot authorize another mutation. State and workflow tasks
preserve the existing owner, revision, native evaluator and evidence-consumption checks.

Use `session_status` for installation/activation/policy/ownership diagnostics and `session_inspect`
or `turn_inspect` for kernel details. `worktree_claim` uses the current worktree and native actor;
release requires the observed lease epoch and fencing token. Material tasks prepare and reconcile
exact local actions from actual invocation/readback evidence; they are not shell or file-edit tools.
Workflow, phase, adaptive and evaluation tasks accept typed domain data, not arbitrary state patches.

An actual change to a Git-scoped file prepared with `material_prepare` leaves a project `check`
obligation. Later material batches and checkpoints cannot erase it. A successful
`verification_run(check="check")` must match the current source and configuration and revalidate
the caller's authority. Read-only turns, preparations with no file changes and Git-ignored private
artifacts do not require this check. Missing bindings or unsupported execution policies remain
explicitly incomplete. Stop combines verification and handoff guidance while retaining its bounded
continuation budget. This confirms the registered project check; goal-specific native round trips
and independent review still require their own explicit acceptance criteria.

## Reduce calls and response size

The default `session_status(detail="summary")` returns installation, activation, policy,
ownership and next actions. `detail="full"` also returns the capability catalog. The internal
CLI retains its detailed result. Shared guidance appears once in MCP initialization
`instructions`. Native identity, policy and ownership checks remain enforced even when
a host does not display that guidance.

| Similar operations | Selection and consolidation decision |
| --- | --- |
| `session_status`, `session_inspect`, `turn_inspect` | Readiness and kernel detail serve different purposes. Start normal preparation with one summary. |
| `collaboration_message`, `collaboration_inbox`, `collaboration_ack`, `collaboration_reply` | Do not fetch a body already received. When replying, use `collaboration_reply`, which includes acknowledgement. |
| `verification_run`, `verification_builtin`, `verification_nodes` | Project bindings, built-in checks and exact nodes have different inputs and evidence contracts. Keep their names and handle failure consistently. |
| `phase_*`, `workflow_*`, `evaluation_*`, `review_*` | Progression, independent evaluation and review acceptance have distinct authority. Do not merge them into a free-form executor. |
| `releases_*`, `installation_*` | Release verification and user choice retain contracts distinct from local installation planning and application. |

Pass public nodes such as `tests/test_example.py::test_example` to `verification_nodes`.
Use the file path from `targets` directly in `material_prepare.expectations[].observable_id`,
without a `file:` prefix.

After fetching bodies through `collaboration_inbox`, acknowledge them in one call using
the existing `collaboration_ack` tool's `message_ids` array. Single `message_id` calls remain
supported. Both forms together, an unread body or a foreign recipient rejects the entire batch.

Codex installation writes `tool_timeout_sec=3660`, above the verifier's maximum 3600 seconds.
Existing connections may need reloading. A transport timeout does not establish process
termination: inspect execution before another check. This does not accelerate checks or change
other hosts' connection limits.

Failed built-in and node checks return MCP errors with exit code, output digest, before/after
fingerprints and bounded diagnostics. A completed failure is not executed again on same-key
replay. Diagnostic text appears only in the first response and is excluded from durable state.
Use a new key for a new check after fixing the cause. Uncertain execution still requires inspection.

Memory synchronization reads bounded native records first, then records events and learning
observations in order within one transaction. Replay retains source conflict checks; a conflict
rolls back the batch. Synthetic processing improvements do not establish an end-to-end LLM
session speedup or token cost reduction.

## Plan and run independent work

1. Discover provider/model capabilities with `provider_capabilities` and `provider_models`.
   Model inventory records are stored, so `provider_models` is not classified as a pure read.
2. Create a selection plan with `provider_plan`: assignment/revision, inventory ID, execution
   settings, selection, constraints, difficulty, evidence/confidence, rationale, alternatives,
   replan triggers and key. Use `provider_plan_read` to read its exact revision.
3. Call `provider_run` with provider/worktree/assignment/key and the plan binding. Its default
   `mode="inherit"` resolves the immediate creator policy. Model/reasoning and explicit policy
   fields must match the selected plan and inherited policy. Supplying fields is not an override grant.
4. Process creator-linked reports. `provider_status` is event-driven diagnosis; `provider_cancel`
   requests cancellation; `provider_recover(run_id, key)` requests recorded-session restoration
   after the native process and connection are verified closed. Recovery is not original-task replay.

Durable run admission returns before model completion. Installation, actual mode, native activation,
ownership and model readback precede implementation. Codex and Claude fields retain provider-specific
meaning; see [Provider transports](provider-transports.md) for supported mapping and readiness limits.
Claude inventory uses a short official SDK control handshake with inherited settings and no model
query. Catalog metadata is not successful authentication or inference. Missing capabilities,
prices and configured defaults remain unknown.

## Messages, acknowledgement and repair

Discover the exact recipient, then use `collaboration_send` or `collaboration_assign`. Assigning a
peer task is distinct from creating a process. Accept the task in the actual native turn and report
major states with `collaboration_report`. The issuer owns body retrieval and subsequent action.

An accepted peer message is durable before notification. Use the stable message ID for full-body
lookup, ACK, reply and diagnostics. `collaboration_ack` and `collaboration_reply` require prior full
body receipt; notification previews do not count. ACK is not task-result acceptance. The delivery
service may resend the same ID/content until ACK; uncertain transport submission is retryable.
Do not turn message retry into periodic completion polling or a separate receiving LLM.

`delivery_status(message_id)` inspects message state, recent attempts and any repair hold.
`delivery_redrive` takes message_id/expected_revision/repair_reference/key and makes a repaired
hold eligible without changing identity or content. Delivery checks still apply. Retained pending
messages survive conversation TTL; `collaboration_close` reports pending rather than silently
losing them. Newsroom has its separate active-only title/body and revision/comment operations.

## Maintenance and native execution limits

Learning status/history/pending are diagnostics; deferral records a reason, not a successful check
or manual promotion. Update/report tasks retain existing version/digest/preview/privacy/consent
and recovery requirements. `releases_check` performs network/local-state work and `releases_notice`
records notice consumption; neither is a pure read. Submission uses the configured fixed destination
and the existing common-report consent or exact contribution approval.

Use `maintenance_choice_prepare` to bind an exact offer, contribution draft or reporting preference
to a reviewable question. After displaying it, `releases_choose`, `reporting_consent` or
`reporting_approve` validates the fresh native user response against that question, its target
snapshot and the kernel prompt receipt. `maintenance_choice_read` distinguishes admitted decisions
from completed application. Tool output, peer messages and unrelated replies cannot authorize a
choice. Unsupported native input formats produce a precise error; preserve an existing approval
through a supported native route rather than asking again automatically. A forced metadata refresh
needs the user's explicit request and the current execution policy, not a second consent question.

Command/network-bearing MCP operations require actual native root ownership and execution policy.
The current direct Codex gate requires ready execution, `danger-full-access`, `never`, and reviewer
`None` or `user`. The Claude gate requires ready execution, `bypassPermissions`, no known native deny
controls, and no observed restrictive filesystem/network control. An `unobserved` ambient OS boundary
is not relabeled unrestricted. This is narrower than the set of modes accepted by the provider adapter;
supporting a mode in a schema does not prove MCP can enforce every restriction of that mode.

`native-execution-required` means this operation cannot enforce the currently observed mode.
Inspect `session_status` and report the specific unsupported state. Do not replay through another transport
or widen settings. Named-tool availability and actual execution remain separate observations.

Uncertain task creation, maintenance or material effects are reconciled through recorded outcomes;
changing to CLI is not permission to execute those effects again. This is separate from at-least-once
message delivery. The legacy server/tool remains compatible for saved clients, while active
instructions and error recovery should select the equivalent named task when exposed.

## Validation

The source modules are `runtime/task_schema.py`, `tasks.py`, `state_tasks.py`, `workflow_tasks.py`,
`maintenance_tasks.py`, `user_choices.py`, `model_tasks.py` and `communication_schema.py`. Schema tests, dispatch/kernel
checks, package installation and fresh-host tool selection are separate evidence. Preserve actual
inventories/calls/results/exceptions privately. Validate installed Codex/Claude natural-language
runs, model planning and post-turn report round trips independently; 132 registrations alone do
not establish that these acceptance scenarios have passed.

## Workflows and additional capabilities

`artifact_put/read` stores and reads bounded session JSON without a caller-selected path.
`enclave_read/set/delete` edits context against the actual turn and digest; `turn_yield` explicitly yields
the current turn. Foreground recovery belongs to host lifecycle events.

`phase_evidence_prepare` produces evidence for the current labels and revision; `phase_complete` accepts
the returned reference. Labels and prose cannot create independent evaluation authority.
Additional observations may use `supplemental_<name>` reports while retaining the existing minimum count and validators.

`installation_plan` returns a reviewable summary and immutable plan reference; `installation_apply` applies
that registered plan. Original file contents remain private. `installation_recover` uses actual journal recovery,
distinguishing damaged placement from integrity of the running package.

`verification_builtin` accepts a closed built-in check kind, `verification_nodes` exact test nodes, and
`verification_run` a project-bound check name. `incident_*` retains incident processing and regression outcomes;
`review_*` retains frozen review matrices and result consumption. `review_comments` bounds results with
limit, offset, since and last_seen. Offset applies to the current remote list at each request; it is not a frozen snapshot cursor.

The `tool` and `arguments` wrappers below document MCP call names and arguments. Native binding fields are
supplied by the host, never authored by the agent.

```json
{"tool":"phase_current","arguments":{"workflow_id":"current-work"}}
```

```json
{"tool":"phase_evidence_prepare","arguments":{"workflow_id":"current-work","expected_revision":0,"labels":["git_status"],"notes":[{"label":"diff_review","text":"Reviewed the purpose and scope of the current change."}],"key":"review-current-diff"}}
```

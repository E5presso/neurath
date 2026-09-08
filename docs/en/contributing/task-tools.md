# Shared task execution

**English** · [한국어](../../ko/contributing/task-tools.md)

[Contributing](index.md) · [Architecture](architecture.md) · [Provider transports](provider-transports.md)

The current source registers **88 named tasks** in `runtime/task_schema.py` and its domain modules.
Registration is not proof that an existing host has reloaded every tool or that all paths have
passed installed-host acceptance. [Model planning and MCP operation](model-planning-mcp.md) and
[Provider collaboration](collaboration-contract.md) define the required behavior.

Named MCP tools are the agent-facing interface. `runtime/tasks.py` dispatches their structured
input to existing stores and kernel services without requiring an agent to assemble CLI argv.
CLI compatibility remains for saved callers and justified native execution exceptions. It is
not the normal workflow, and an arbitrary `agent(argv)` gateway does not count as migration.

## Registered source surface

This inventory groups the exact registered names. Read each exposed input schema before calling;
not every operation in a group has the same input or authority.

| Domain | Named tasks |
| --- | --- |
| Readiness | `session_status` |
| Provider execution and recovery | `provider_run`, `provider_status`, `provider_cancel`, `provider_recover` |
| Provider route discovery | `provider_capabilities`, `provider_route` |
| Memory and handoff | `memory_recall`, `memory_checkpoint` |
| Registered checks | `verification_run` |
| Peer messages and subscriptions | `collaboration_discover`, `collaboration_inbox`, `collaboration_send`, `collaboration_reply`, `collaboration_message`, `collaboration_ack`, `collaboration_forward`, `collaboration_submitted`, `collaboration_register`, `collaboration_conversation`, `collaboration_close`, `collaboration_subscribe`, `collaboration_unsubscribe`, `collaboration_publish` |
| Assigned task lifecycle | `collaboration_assign`, `collaboration_accept`, `collaboration_report`, `collaboration_task` |
| Newsroom | `newsroom_headlines`, `newsroom_read`, `newsroom_publish`, `newsroom_revise`, `newsroom_comment`, `newsroom_peers`, `newsroom_seen` |
| State, ownership and material actions | `session_inspect`, `turn_inspect`, `worktree_inspect`, `worktree_claim`, `worktree_release`, `material_prepare`, `material_read`, `material_resolve`, `material_abandon` |
| Learning, updates and reporting | `learning_status`, `learning_pending`, `releases_status`, `reporting_status`, `reporting_list`, `learning_history`, `learning_defer`, `reporting_read`, `releases_check`, `releases_notice`, `releases_recover`, `releases_prepare`, `releases_apply`, `reporting_prepare`, `reporting_submit`, `reporting_reconcile`, `reporting_consent`, `reporting_approve`, `releases_choose` |
| Model inventory and plans | `provider_models`, `provider_plan`, `provider_plan_read` |
| Workflow, phases, delegation and evaluation | `workflow_start`, `workflow_advance`, `workflow_finalize`, `phase_start`, `phase_current`, `phase_complete`, `phase_finalize`, `adaptive_read`, `adaptive_preflight`, `adaptive_replace`, `adaptive_override_goal`, `delegation_prepare`, `delegation_assign`, `evaluation_prepare`, `evaluation_read`, `evaluation_execute`, `evaluation_report`, `evaluation_consume` |
| Message repair | `delivery_status`, `delivery_redrive` |
| Exact maintenance choices | `maintenance_choice_prepare`, `maintenance_choice_read` |

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

When the task returns `native-execution-required`, the agent must preserve policy and use the
supported native execution route for the same authorized operation. Record the operation, tool
availability, reason and actual result as a migration exception. Do not widen settings or evade a
deny. Ordinary source-edit/test shell work is distinct from agent-operated harness commands.

Uncertain task creation, maintenance or material effects are reconciled through recorded outcomes;
changing to CLI is not permission to execute those effects again. This is separate from at-least-once
message delivery. The legacy server/tool remains compatible for saved clients, while active
instructions and error recovery should select the equivalent named task when exposed.

## Validation

The source modules are `runtime/task_schema.py`, `tasks.py`, `state_tasks.py`, `workflow_tasks.py`,
`maintenance_tasks.py`, `user_choices.py`, `model_tasks.py` and `communication_schema.py`. Schema tests, dispatch/kernel
checks, package installation and fresh-host tool selection are separate evidence. Preserve actual
inventories/calls/results/exceptions privately. Validate installed Codex/Claude natural-language
runs, model planning and post-turn report round trips independently; 88 registrations alone do
not establish that these acceptance scenarios have passed.

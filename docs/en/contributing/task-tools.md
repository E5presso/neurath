# Shared task execution

<!-- date: 2026-09-09; synced_from: baseline f69cb6402683bb2e0bfe56ed04c63f808b263f06 plus current working-tree stdio MCP changes; scope: source, not live-host certification -->

**English** · [한국어](../../ko/contributing/task-tools.md)

[Contributing](index.md) · [Architecture](architecture.md) · [Provider transports](provider-transports.md)

The current source registers **130 public tools (137 internal compatibility operations)** in `runtime/task_schema.py` and its domain modules.
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
| Tasks | `task_define`, `task_list`, `task_resolve`, `task_start` |
| Harness bypass | `harness_bypass` |
| Session readiness | `session_status` |
| Independent execution | `provider_cancel`, `provider_recover`, `provider_run`, `provider_status` |
| Provider discovery | `provider_capabilities`, `provider_route` |
| Memory | `memory_checkpoint`, `memory_recall` |
| Peer communication | `collaboration_ack`, `collaboration_close`, `collaboration_conversation`, `collaboration_discover`, `collaboration_forward`, `collaboration_inbox`, `collaboration_message`, `collaboration_publish`, `collaboration_register`, `collaboration_reply`, `collaboration_send`, `collaboration_submitted`, `collaboration_subscribe`, `collaboration_unsubscribe` |
| Assigned task lifecycle | `collaboration_accept`, `collaboration_assign`, `collaboration_report`, `collaboration_task` |
| Newsroom | `newsroom_comment`, `newsroom_headlines`, `newsroom_peers`, `newsroom_publish`, `newsroom_read`, `newsroom_revise`, `newsroom_seen` |
| State, artifacts and ownership | `artifact_put`, `artifact_read`, `session_inspect`, `turn_inspect`, `worktree_claim`, `worktree_inspect`, `worktree_release` |
| Learning, releases and reporting | `learning_defer`, `learning_history`, `learning_pending`, `learning_status`, `maintenance_choice_prepare`, `maintenance_choice_read`, `releases_apply`, `releases_check`, `releases_choose`, `releases_notice`, `releases_prepare`, `releases_recover`, `releases_status`, `reporting_approve`, `reporting_consent`, `reporting_list`, `reporting_prepare`, `reporting_read`, `reporting_reconcile`, `reporting_status`, `reporting_submit` |
| Model planning | `provider_models`, `provider_plan`, `provider_plan_read` |
| Phases and evaluation | `adaptive_override_goal`, `adaptive_preflight`, `adaptive_read`, `adaptive_replace`, `delegation_assign`, `delegation_prepare`, `evaluation_consume`, `evaluation_execute`, `evaluation_prepare`, `evaluation_read`, `evaluation_report`, `phase_complete`, `phase_current`, `phase_evidence_prepare`, `phase_finalize`, `phase_start`, `workflow_advance`, `workflow_finalize`, `workflow_start` |
| Context, enclave and evaluation loops | `diagnostics_integrity`, `diagnostics_profile`, `diagnostics_project`, `enclave_delete`, `enclave_read`, `enclave_set`, `evaluation_loop_close`, `evaluation_loop_open`, `evaluation_loop_read`, `evaluation_loop_round`, `turn_yield` |
| Verification, incidents and reviews | `diagnostics_continuation`, `incident_escalate`, `incident_record`, `incident_refresh`, `incident_resolve`, `incident_supersede`, `incident_validate`, `review_abort`, `review_begin`, `review_comments`, `review_consume`, `review_publish`, `review_report` |
| Installation administration | `installation_apply`, `installation_plan`, `installation_recover` |
| Process evidence and cleanup | `process_evidence_record`, `worktree_cleanup`, `worktree_isolation` |
| PR monitoring | `monitor_ack`, `monitor_cancel`, `monitor_event`, `monitor_external_wait`, `monitor_handoff`, `monitor_readback`, `monitor_recover`, `monitor_start`, `monitor_status` |
| Delivery recovery | `delivery_redrive`, `delivery_status` |

## Normal work

Use `session_status` once for installation, native activation, policy and ownership.
Claim the current worktree normally. Record work with `task_define`, `task_start` and
`task_resolve`; reuse the returned IDs and revisions. Completion is one owner report
with a terminal status, summary and references. A task ledger is checked atomically
when the root turn closes. The native TODO display is a projection, not another gate.

Edit files and run the project checks through native host tools. Material batches,
verification debt, repeated acceptance JSON, learning and checkpoints do not add
completion gates. Existing workflow and evaluator operations remain available for
explicit workflows and recovery of their saved records. Do not create another
workflow just to resolve a task. See [Tasks and session completion](task-todo-contract.md).

## Bypass

`harness_bypass` accepts `enabled=true`, `false`, or an omitted/null value to read.
It affects only the configured worktree. Enabling it suspends all Neurath hooks;
disabling it restores normal dispatch. Host permissions and user instructions remain
in force. The switch needs no native binding or worker slot, including when turning
itself off. Ordinary MCP tools still require authentic native bindings. A session
started during bypass must establish normal native activation after restoring hooks.

## Fewer calls and smaller results

MCP responses carry data once in `structuredContent` and a short text summary.
Task mutations return IDs, revisions, statuses and the native TODO instruction;
retry bookkeeping stays in storage. Use `task_list` when the full list is needed,
not as a repeated confirmation of a successful mutation.

Reuse message bodies already received. `collaboration_reply` acknowledges and replies
atomically; inbox reads can be acknowledged together with `collaboration_ack.message_ids`.
Batch sends use `collaboration_send.messages`. Queued delivery, acknowledgement and
reviewed results remain distinct. Do not poll an idle peer or create a receiver session.

Automatic memory context appears only at SessionStart, bounded to 3 KB. Later prompts
retain their history without repeatedly injecting old patches or tool results.

## Installation and compatibility

Source registration, installation, loaded MCP tools and actual native execution are
separate observations. Installing a new immutable runtime does not replace an existing
MCP process. Stop old writers before a shared-store cutover, install the source, then
reload the host connection and verify its actual tools and hooks. Never patch an
immutable installed runtime or manufacture a native binding.

`material_*`, `verification_*` and the old `agent(argv)` adapter are internal compatibility
interfaces omitted from discovery. Their presence does not require prepare/resolve
round trips for ordinary editing and testing. Ownership, native identity, revisions
and the host's permission policy still apply to exposed operations.

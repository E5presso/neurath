<!-- last_updated: 2026-09-14; synced_from: 243400e58ca74c7fd79bcdd86b488953fa743b97 -->
# Find a capability by the work it supports

[한국어](../../ko/contributing/capability-map.md)

Start with the user's result, then select the tools needed to carry it through. A **task** records that result and its acceptance conditions. The native **root actor** owns the task list in a **session**. A **worktree claim** coordinates the checkout owner. A **receipt** records an event or report. A workflow **phase** organizes a procedure, and a **review** assesses a defined scope. [Architecture](architecture.md) explains how these objects fit together.

For a user's web application whose saved filter disappears after reload, the main path is task intake, native reproduction and implementation, relevant API review, evidence, and resolution. Memory and learning help retain the reproduction and correct test command. Provider execution, public reporting, release installation, and monitoring enter only when the request or selected workflow needs them.

This catalog covers all **128 public named tools** in the current source. There are **138 internal operations**; saved-call compatibility and internal material/verification operations are not additional public tools. The table lists required top-level arguments and whether the schema labels the operation read-only. Optional arguments, nested shapes and domain prerequisites remain part of the discovered schema. A read-only label grants no authority; a state-changing label does not mean the tool edits product files.

Native hooks supply `_neurath_binding`; it is omitted below because the agent must not invent it. Except for `harness_bypass`, the named operations require a valid native invocation and are unavailable during bypass. Use [task tools](task-tools.md) for input, error and retry conventions.

## Establish the current session and ownership

A session is the native conversation; its root actor owns the task list. A worktree claim coordinates the checkout owner. Inspect before claiming. Isolation verifies an existing issue/root topology and does not create or switch worktrees. Cleanup needs actual branch/ref and ownership evidence. Bypass changes Neurath hook constraints only; omitting enabled reads, true bypasses, and false restores. Host permissions and history remain intact.

| Tool | Schema effect | Required arguments |
| --- | --- | --- |
| `harness_bypass` | State change | None |
| `session_status` | Read | None |
| `session_inspect` | Read | None |
| `turn_inspect` | Read | None |
| `worktree_inspect` | Read | None |
| `worktree_claim` | State change | None |
| `worktree_release` | State change | `expected_lease_epoch`, `fencing_token` |
| `worktree_isolation` | State change | `issue_number`, `key` |
| `worktree_cleanup` | State change | `workflow_id`, `base_branch`, `remote_ref`, `key` |

## Record measurable work

A task binds a goal, instruction sources and acceptance conditions. Define necessary work, start with returned revisions, and resolve an observed owner report. The list distinguishes terminal execution from successful outcomes and supplies the native TODO projection. See [task tools](task-tools.md) and the [task contract](task-todo-contract.md).

| Tool | Schema effect | Required arguments |
| --- | --- | --- |
| `task_define` | State change | `tasks`, `expected_revision`, `key` |
| `task_list` | Read | None |
| `task_start` | State change | `task_id`, `expected_revision`, `expected_task_revision`, `key` |
| `task_resolve` | State change | `task_id`, `expected_revision`, `expected_task_revision`, `key`, `status`, `references`, `summary` |

## Organize a skill procedure and its decisions

A workflow is a skill run; a phase is a step in its procedure. Read the selected contract before advancing it. Evidence binds the exact current phase/revision. Adaptive decisions and goal changes need their applicable authority, and a yield label does not waive Stop prerequisites. Public skill names and stable internal contract IDs are mapped in [skills reference](skills-reference.md).

| Tool | Schema effect | Required arguments |
| --- | --- | --- |
| `phase_start` | State change | `workflow_id`, `key`, `skill`, `run_id`, `north_star` |
| `phase_current` | Read | `workflow_id` |
| `phase_evidence_prepare` | State change | `workflow_id`, `expected_revision`, `key` |
| `phase_complete` | State change | `workflow_id`, `expected_revision`, `key`, `phase_id`, `status`, `summary` |
| `phase_finalize` | State change | `workflow_id`, `expected_revision`, `key`, `terminal_state` |
| `adaptive_read` | Read | `workflow_id` |
| `adaptive_preflight` | Read | None |
| `adaptive_replace` | State change | `workflow_id`, `expected_revision`, `key`, `state` |
| `adaptive_override_goal` | State change | `workflow_id`, `expected_revision`, `key`, `state` |
| `turn_yield` | State change | `expected_turn_revision`, `outcome`, `key` |

## Delegate and evaluate a bounded candidate

Delegation gives a participant a bounded assignment. Preparation creates spawn intent, not execution. Independent evaluation additionally requires a verified role, exact candidate and authenticated report consumption. Source, goal, intent, owner or revision changes can invalidate an old candidate report. Evaluation loops retain their explicit open/round/close contract.

| Tool | Schema effect | Required arguments |
| --- | --- | --- |
| `delegation_prepare` | State change | `delegation_id`, `assignment`, `key` |
| `delegation_assign` | State change | `workflow_id`, `delegation_id`, `assignment`, `target`, `key` |
| `evaluation_prepare` | State change | `workflow_id`, `key`, `state` |
| `evaluation_read` | Read | `workflow_id`, `assignment` |
| `evaluation_execute` | State change | `workflow_id`, `key`, `state`, `criterion_id`, `evidence_kind`, `pytest_node` |
| `evaluation_report` | State change | `delegation_id`, `key`, `verdict`, `summary`, `outcome_ref` |
| `evaluation_consume` | State change | `delegation_id`, `key` |
| `evaluation_loop_open` | State change | `workflow_id`, `loop_id`, `goal`, `acceptance`, `key` |
| `evaluation_loop_read` | Read | `workflow_id`, `loop_id` |
| `evaluation_loop_round` | State change | `workflow_id`, `loop_id`, `number`, `findings`, `key` |
| `evaluation_loop_close` | State change | `workflow_id`, `loop_id`, `outcome`, `summary`, `key` |

## Obtain and consume a review

A review assesses a stated scope. Begin with the reviewer and relevant head, receive a report, and consume the exact outcome. Publication checks the current PR head and review scope; a consumed review is not automatic authorization to publish. In the filter example, API review supplies evidence alongside implementation and save/reload regression.

| Tool | Schema effect | Required arguments |
| --- | --- | --- |
| `review_begin` | State change | `workflow_id`, `to`, `kind`, `label`, `scope`, `key` |
| `review_report` | State change | `workflow_id`, `delegation_id`, `verdict`, `summary`, `key` |
| `review_consume` | State change | `workflow_id`, `delegation_id`, `outcome_ref`, `key` |
| `review_abort` | State change | `workflow_id`, `delegation_id`, `outcome_ref`, `key` |
| `review_publish` | State change | `workflow_id`, `repo`, `pr_number`, `key` |
| `review_comments` | State change | `repo`, `pr_number` |

## Choose and run an independent provider

Use actual model inventory, a revisioned plan, then its exact run. Model selection inherit differs from execution policy inherit. Target-native requires its own explicit choice and preserves destination settings. Verify actual model, policy, activation, tools and ownership before assignment. Status is event/failure diagnosis, not completion polling. See [model planning](model-planning-mcp.md) and [provider transports](provider-transports.md).

| Tool | Schema effect | Required arguments |
| --- | --- | --- |
| `provider_models` | State change | `provider` |
| `provider_plan` | State change | `provider`, `worktree`, `assignment`, `inventory_id`, `execution`, `selection`, `difficulty`, `confidence`, `rationale`, `key` |
| `provider_plan_read` | Read | `plan_id` |
| `provider_capabilities` | Read | `provider` |
| `provider_route` | Read | `provider`, `operation` |
| `provider_run` | State change | `worktree`, `assignment` |
| `provider_status` | Read | `run_id` |
| `provider_cancel` | State change | `run_id` |
| `provider_recover` | State change | `run_id`, `key` |

## Exchange authenticated peer messages

Discover exact recipients and send only authorized communications. Read the full message before ACK. Queued admission, native notification submission, recipient acknowledgement, assignment acceptance and task completion are separate observations. Repair preserves the original message identity; an old delivery generation cannot undo a newer ACK. See [collaboration contract](collaboration-contract.md).

| Tool | Schema effect | Required arguments |
| --- | --- | --- |
| `collaboration_register` | State change | `name` |
| `collaboration_discover` | Read | None |
| `collaboration_inbox` | Read | None |
| `collaboration_send` | State change | None |
| `collaboration_reply` | State change | `message_id`, `message`, `key` |
| `collaboration_message` | Read | `message_id` |
| `collaboration_ack` | State change | None |
| `collaboration_forward` | Read | `message_id` |
| `collaboration_submitted` | State change | `message_id`, `transport` |
| `collaboration_assign` | State change | `to`, `message`, `key` |
| `collaboration_accept` | State change | `task_id` |
| `collaboration_report` | State change | `task_id`, `state`, `key` |
| `collaboration_task` | Read | `task_id` |
| `collaboration_conversation` | Read | `conversation` |
| `collaboration_close` | State change | `conversation` |
| `collaboration_subscribe` | State change | `to` |
| `collaboration_unsubscribe` | State change | `to` |
| `collaboration_publish` | State change | `message`, `key` |
| `delivery_status` | Read | `message_id` |
| `delivery_redrive` | State change | `message_id`, `expected_revision`, `repair_reference`, `key` |

## Share project discoveries

Newsroom distributes attributed project reference material and discussion. Titles help peers select relevant bodies to read. Articles, comments and seen state do not grant user authority, ownership or task acceptance.

| Tool | Schema effect | Required arguments |
| --- | --- | --- |
| `newsroom_headlines` | Read | None |
| `newsroom_read` | Read | `article_id` |
| `newsroom_publish` | State change | `title`, `body`, `key` |
| `newsroom_revise` | State change | `article_id`, `revision`, `title`, `body`, `key` |
| `newsroom_comment` | State change | `article_id`, `revision`, `body`, `key` |
| `newsroom_peers` | Read | None |
| `newsroom_seen` | State change | `event_id` |

## Retain evidence, context and learned guidance

Artifacts retain bounded JSON evidence; enclave holds revision-checked current facts; memory retains attributed history. Recall and checkpoint are reference/owner reports. Pull adoption is a separate transfer requiring a quiescent source and exact preview. Learning joins a matching failure/recovery and configured verification, then separate-session exposure and success for promotion. The corrected test command must be observed, not merely suggested. See [memory reference](memory-reference.md) and [provider continuity](provider-continuity.md).

| Tool | Schema effect | Required arguments |
| --- | --- | --- |
| `artifact_put` | State change | `document`, `key` |
| `artifact_read` | Read | `reference` |
| `memory_recall` | Read | None |
| `memory_checkpoint` | State change | `summary`, `key` |
| `memory_pull` | State change | None |
| `enclave_read` | Read | None |
| `enclave_set` | State change | `fact_key`, `value`, `expected_digest`, `key` |
| `enclave_delete` | State change | `fact_key`, `expected_digest`, `key` |
| `learning_status` | Read | None |
| `learning_pending` | Read | None |
| `learning_history` | Read | `strategy_id` |
| `learning_defer` | State change | `reason`, `key` |

## Diagnose and repair harness problems

Diagnostics identify the relevant boundary. An incident records a harness problem and its repair or accountable escalation; a label alone cannot prove the fix. Retain actual reproduction, root cause and applicable regression evidence. Placement/protocol diagnostics and native activation remain distinct. See [validation](validation.md).

| Tool | Schema effect | Required arguments |
| --- | --- | --- |
| `diagnostics_integrity` | Read | None |
| `diagnostics_project` | State change | None |
| `diagnostics_profile` | Read | None |
| `diagnostics_continuation` | Read | None |
| `incident_record` | State change | `rule_id`, `symptom`, `key` |
| `incident_validate` | Read | None |
| `incident_resolve` | State change | `incident_id`, `root_cause`, `fixes`, `checks`, `key` |
| `incident_escalate` | State change | `incident_id`, `summary`, `checks`, `key` |
| `incident_refresh` | State change | `incident_ids`, `key` |
| `incident_supersede` | State change | `incident_id`, `fixes`, `checks`, `key` |
| `process_evidence_record` | State change | `workflow_id`, `field`, `value`, `key` |

## Observe authorized ongoing work

A monitor owns a specific observation/resume contract. Admission precedes the first actual observation. It preserves workflow/PR scope, owner policy and process generation. Event ACK consumes an exact event; external_wait preserves an unresolved reviewer-owned event; handoff retires or transfers verified resources. Cancellation needs a terminal result.

| Tool | Schema effect | Required arguments |
| --- | --- | --- |
| `monitor_start` | State change | `workflow_id`, `repo`, `pr_number`, `key` |
| `monitor_status` | Read | `run_id` |
| `monitor_cancel` | State change | `run_id`, `key` |
| `monitor_recover` | State change | `run_id`, `key` |
| `monitor_readback` | Read | `run_id` |
| `monitor_event` | Read | `workflow_id` |
| `monitor_ack` | State change | `workflow_id`, `event_id`, `key` |
| `monitor_external_wait` | State change | `workflow_id`, `event_id`, `key` |
| `monitor_handoff` | State change | `workflow_id`, `pr_number`, `key` |

## Apply a deliberate installation or release choice

Plans bind target/distribution and exact before/after state. Release checks use the fixed official published-release source; automatic hooks only offer a local due hint. A release choice must refer to the actual user response and immutable prepared offer. Apply verifies installation results while subsequent native activation remains unobserved until a real host event. See [installation design](installation-design.md) and [releases reference](releases-reference.md).

| Tool | Schema effect | Required arguments |
| --- | --- | --- |
| `installation_plan` | State change | `key` |
| `installation_apply` | State change | `plan_ref`, `key` |
| `installation_recover` | State change | `key` |
| `releases_status` | Read | None |
| `releases_check` | State change | `key` |
| `releases_notice` | State change | `key` |
| `releases_prepare` | State change | `offer_id`, `key` |
| `releases_choose` | State change | `decision`, `user_choice_ref`, `key`, `offer_id` |
| `releases_apply` | State change | `offer_id`, `key` |
| `releases_recover` | State change | `key` |
| `maintenance_choice_read` | Read | `user_choice_ref` |
| `maintenance_choice_prepare` | State change | `operation`, `key` |

## Prepare a reviewed public report

Reporting uses a fixed upstream destination and private, content-bound drafts. Common reports require the saved explicit project consent; contributions require exact draft approval. Privacy review precedes preparation. An uncertain submission must reconcile its existing remote result before another send. Reporting failure does not replace the original user goal. See [reporting reference](reporting-reference.md).

| Tool | Schema effect | Required arguments |
| --- | --- | --- |
| `reporting_status` | Read | None |
| `reporting_list` | Read | None |
| `reporting_read` | Read | `draft_id` |
| `reporting_prepare` | State change | `report`, `privacy_reviewed`, `key` |
| `reporting_consent` | State change | `decision`, `user_choice_ref`, `key` |
| `reporting_approve` | State change | `decision`, `user_choice_ref`, `key`, `draft_id` |
| `reporting_submit` | State change | `draft_id`, `key` |
| `reporting_reconcile` | State change | `draft_id`, `url`, `key` |

## Follow the returned boundary

A prepared action is not execution, a queued message is not receipt, and a terminal task is not necessarily successful. Choose the next operation from the current result and its `next_action`, retaining exact references, revisions, and operation keys. Source definitions live in `src/neurath/runtime/task_schema.py` and its imported domain modules; `src/neurath/agents/mcp.py` supplies native call admission. The [contributor guide](index.md) connects these references to the development workflow.

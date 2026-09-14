<!-- date: 2026-09-14; synced_from: 655c8768709e59b5e5012bab0adc4d888e3e7fa5 + current working-tree facts -->

[한국어](../../ko/contributing/capability-map.md)

# Find the skill, operation and implementation

Use this map when deciding where a requested behavior belongs or which source and regression contract must change with it. Public skill names describe the agent's work; internal names locate bundled source. Named tools carry durable state operations. A skill name alone is neither a tool call nor proof that its workflow ran.

## Public skill inventory

There are 31 public skills. Twenty-nine have phase contracts. `explain-code` and `graphify` are supporting skills without a phase contract. An installed skill prefix changes the user-visible name while preserving the source identity; for example, prefix `neurath-` projects `debug` as `neurath-debug`.

| Intended work | Public skill | Internal source name | Contract |
| --- | --- | --- | --- |
| security/license/freshness/drift | `audit-deps` | [dependency-audit](../../../src/neurath/_assets/.agents/skills/dependency-audit/SKILL.md) | Phase |
| coordinate explicitly requested multiple issues | `autopilot` | [autopilot](../../../src/neurath/_assets/.agents/skills/autopilot/SKILL.md) | Phase |
| reversible WIP save | `checkpoint` | [checkpoint](../../../src/neurath/_assets/.agents/skills/checkpoint/SKILL.md) | Phase |
| commit authorized verified change | `commit` | [commit](../../../src/neurath/_assets/.agents/skills/commit/SKILL.md) | Phase |
| create approved work items | `create-issue` | [create-ticket](../../../src/neurath/_assets/.agents/skills/create-ticket/SKILL.md) | Phase |
| authorized push and PR | `create-pr` | [create-pr](../../../src/neurath/_assets/.agents/skills/create-pr/SKILL.md) | Phase |
| prepare isolated issue workspace | `create-worktree` | [create-worktree](../../../src/neurath/_assets/.agents/skills/create-worktree/SKILL.md) | Phase |
| reproduce and isolate defects | `debug` | [investigate](../../../src/neurath/_assets/.agents/skills/investigate/SKILL.md) | Phase |
| explore design and obtain exact canvas choice | `design-ui` | [explore-ui](../../../src/neurath/_assets/.agents/skills/explore-ui/SKILL.md) | Phase |
| developer docs | `dev-docs` | [sync-dev-docs](../../../src/neurath/_assets/.agents/skills/sync-dev-docs/SKILL.md) | Phase |
| explain current source/test-backed behavior | `explain-code` | [explain-code](../../../src/neurath/_assets/.agents/skills/explain-code/SKILL.md) | Supporting |
| authorized commit/push/graph update/claim release | `finish-session` | [finish-session](../../../src/neurath/_assets/.agents/skills/finish-session/SKILL.md) | Phase |
| explore code/document relationship graph | `graphify` | [graphify](../../../src/neurath/_assets/.agents/skills/graphify/SKILL.md) | Supporting |
| implement one approved issue | `implement-issue` | [process-ticket](../../../src/neurath/_assets/.agents/skills/process-ticket/SKILL.md) | Phase |
| build exact approved node | `implement-ui` | [implement-ui](../../../src/neurath/_assets/.agents/skills/implement-ui/SKILL.md) | Phase |
| review recurring private knowledge for approved project rule | `memory-to-rules` | [promote-memory](../../../src/neurath/_assets/.agents/skills/promote-memory/SKILL.md) | Phase |
| reduce injected prompt preserving capability | `optimize-harness` | [optimize-harness](../../../src/neurath/_assets/.agents/skills/optimize-harness/SKILL.md) | Phase |
| clarify product decisions and decompose into docs/issues | `plan` | [plan-issues](../../../src/neurath/_assets/.agents/skills/plan-issues/SKILL.md) | Phase |
| assess/respond to review comments | `pr-feedback` | [triage-comments](../../../src/neurath/_assets/.agents/skills/triage-comments/SKILL.md) | Phase |
| verify deployed interface/API/persisted result | `qa` | [automate-qa](../../../src/neurath/_assets/.agents/skills/automate-qa/SKILL.md) | Phase |
| find evidenced defects in changes | `review-code` | [review-code](../../../src/neurath/_assets/.agents/skills/review-code/SKILL.md) | Phase |
| publish verified local review at exact PR head | `review-pr` | [pr-review](../../../src/neurath/_assets/.agents/skills/pr-review/SKILL.md) | Phase |
| audit requirements before implementation | `review-spec` | [audit-spec](../../../src/neurath/_assets/.agents/skills/audit-spec/SKILL.md) | Phase |
| compare approved design and runtime for user judgment | `review-ui` | [review-ui](../../../src/neurath/_assets/.agents/skills/review-ui/SKILL.md) | Phase |
| repository tokens/component mappings into canvas | `sync-design` | [sync-design](../../../src/neurath/_assets/.agents/skills/sync-design/SKILL.md) | Phase |
| route documentation scope | `sync-docs` | [sync-docs](../../../src/neurath/_assets/.agents/skills/sync-docs/SKILL.md) | Phase |
| failure scenarios verify enforcement | `test-harness` | [evaluate-harness](../../../src/neurath/_assets/.agents/skills/evaluate-harness/SKILL.md) | Phase |
| controlled updates/checks | `update-deps` | [update-dependencies](../../../src/neurath/_assets/.agents/skills/update-dependencies/SKILL.md) | Phase |
| issue/project metadata | `update-status` | [update-project-status](../../../src/neurath/_assets/.agents/skills/update-project-status/SKILL.md) | Phase |
| approved implemented user behavior | `user-docs` | [sync-user-docs](../../../src/neurath/_assets/.agents/skills/sync-user-docs/SKILL.md) | Phase |
| observe PR changes | `watch-pr` | [monitor-pr](../../../src/neurath/_assets/.agents/skills/monitor-pr/SKILL.md) | Phase |

Implementation uses the source under `src/neurath/_assets/.agents/skills`; installed `.agents/skills` and `.neurath/rules` are projections. The name mapping lives in [skill_names.py](../../../src/neurath/skill_names.py). Publication checks verify the public catalog, locale layout and package contents.

Standalone names `create-package`, `local-dev`, `onboard`, `refactor-code`, `impact-analysis`, `improve-coverage` and `property-test` are retired from the public skill inventory. Do not advertise them as installed standalone capabilities. Route the actual request through the applicable current skill and project procedure.

## Public tool families

The current discovery schema exposes 128 public tools. This table lists every one once. The internal dispatch count is 138 and is a different scope: saved-call compatibility includes operations that discovery no longer advertises. Use the installed `tools/list` schema for exact fields and [task tools](task-tools.md) for the common envelope and core examples.

| Purpose | Named tools |
| --- | --- |
| Requested work and current session | `harness_bypass`, `session_status`, `session_inspect`, `turn_inspect`, `turn_yield`, `task_define`, `task_list`, `task_start`, `task_resolve` |
| Worktree ownership | `worktree_inspect`, `worktree_claim`, `worktree_release`, `worktree_isolation`, `worktree_cleanup` |
| Provider choice and execution | `provider_run`, `provider_status`, `provider_cancel`, `provider_recover`, `provider_capabilities`, `provider_route`, `provider_models`, `provider_plan`, `provider_plan_read` |
| Peer messages and assignments | `collaboration_discover`, `collaboration_inbox`, `collaboration_send`, `collaboration_reply`, `collaboration_message`, `collaboration_ack`, `collaboration_forward`, `collaboration_submitted`, `collaboration_assign`, `collaboration_accept`, `collaboration_report`, `collaboration_task`, `collaboration_register`, `collaboration_conversation`, `collaboration_close`, `collaboration_subscribe`, `collaboration_unsubscribe`, `collaboration_publish` |
| Delivery repair | `delivery_status`, `delivery_redrive` |
| Shared announcements | `newsroom_headlines`, `newsroom_read`, `newsroom_publish`, `newsroom_revise`, `newsroom_comment`, `newsroom_peers`, `newsroom_seen` |
| Memory and session facts | `memory_recall`, `memory_checkpoint`, `memory_pull`, `artifact_put`, `artifact_read`, `enclave_read`, `enclave_set`, `enclave_delete` |
| Learning | `learning_status`, `learning_pending`, `learning_history`, `learning_defer` |
| Contracted phases | `phase_start`, `phase_current`, `phase_evidence_prepare`, `phase_complete`, `phase_finalize` |
| Adaptive decisions and independent evaluation | `adaptive_read`, `adaptive_preflight`, `adaptive_replace`, `adaptive_override_goal`, `delegation_prepare`, `delegation_assign`, `evaluation_prepare`, `evaluation_read`, `evaluation_execute`, `evaluation_report`, `evaluation_consume`, `evaluation_loop_open`, `evaluation_loop_read`, `evaluation_loop_round`, `evaluation_loop_close` |
| Fixed review and publication | `review_begin`, `review_report`, `review_consume`, `review_abort`, `review_publish`, `review_comments` |
| Diagnostics and incidents | `diagnostics_integrity`, `diagnostics_project`, `diagnostics_profile`, `diagnostics_continuation`, `incident_record`, `incident_validate`, `incident_resolve`, `incident_escalate`, `incident_refresh`, `incident_supersede`, `process_evidence_record` |
| Installation and releases | `releases_status`, `releases_check`, `maintenance_choice_read`, `maintenance_choice_prepare`, `releases_notice`, `releases_recover`, `releases_prepare`, `releases_apply`, `releases_choose`, `installation_plan`, `installation_apply`, `installation_recover` |
| Public reporting | `reporting_status`, `reporting_list`, `reporting_read`, `reporting_prepare`, `reporting_submit`, `reporting_reconcile`, `reporting_consent`, `reporting_approve` |
| Background observation | `monitor_start`, `monitor_status`, `monitor_cancel`, `monitor_recover`, `monitor_readback`, `monitor_event`, `monitor_ack`, `monitor_external_wait`, `monitor_handoff` |

`phase_start`, `phase_complete` and `phase_finalize` are the public lifecycle entry points. The former workflow names remain compatible with saved calls. Material batches, registered-verification tools and `agent(argv)` are also compatibility surfaces rather than public requirements for ordinary edits and checks.

## Choose the correct authority

| Situation | Contract to follow |
| --- | --- |
| Ordinary measurable task | Define the work, perform native edits/checks, record the owner result once. The task list governs Stop when present. |
| Explicit adaptive skill | Establish actual independent evaluator authority, bind the exact candidate and consume its authentic result before the contracted transition. |
| Fixed code or PR review | Apply its separate review matrix; publishing binds the current PR head. |
| Peer assignment | Discover the real peer, deliver the complete assignment, obtain native acceptance and report; acknowledgement alone is transport progress. |
| Worktree change or cleanup | Use the current owner lease and returned fencing generation; verify real Git references before cleanup. |
| Installation, update or reporting | Prepare the exact change or draft, retain applicable user choice, apply through the named domain operation and inspect its actual outcome. |

The [task and TODO contract](task-todo-contract.md), [runtime lifecycle](runtime-lifecycle.md) and [host integration](hosts.md) explain the state and native evidence behind these choices.

## Implementation and regression ownership

These links locate the code and tests that own each behavior. They identify verification scope, not a claim that those tests or live-host scenarios passed for a particular installation.

| Responsibility | Implementation and regression contracts |
| --- | --- |
| Bundled asset integrity | [resources.py](../../../src/neurath/resources.py), [manifest.json](../../../src/neurath/manifest.json), [test_installer.py](../../../tests/test_installer.py) |
| Installation preservation | [projection.py](../../../src/neurath/install/projection.py), [transaction.py](../../../src/neurath/install/transaction.py), [test_installer.py](../../../tests/test_installer.py), [test_publication.py](../../../tests/test_publication.py) |
| Native identity and prompts | [identity.py](../../../src/neurath/hosts/identity.py), [hooks.py](../../../src/neurath/hosts/hooks.py), [test_host_lifecycle.py](../../../tests/test_host_lifecycle.py), [test_prompt_delivery.py](../../../tests/test_prompt_delivery.py) |
| State and writer ownership | [session_kernel.py](../../../src/neurath/_assets/scripts/agent_harness/session_kernel.py), [state_handle.py](../../../src/neurath/_assets/scripts/agent_harness/state_handle.py), [worktree_registry.py](../../../src/neurath/_assets/scripts/agent_harness/worktree_registry.py), [runtime_database.py](../../../src/neurath/_assets/scripts/agent_harness/runtime_database.py), [test_session_kernel.py](../../../tests/runtime/agent_harness/test_session_kernel.py), [test_worktree_registry.py](../../../tests/runtime/agent_harness/test_worktree_registry.py) |
| Requested work and outcomes | [task_ledger_tasks.py](../../../src/neurath/runtime/task_ledger_tasks.py), [task_ledger.py](../../../src/neurath/_assets/scripts/agent_harness/task_ledger.py), [task_service.py](../../../src/neurath/_assets/scripts/agent_harness/task_service.py), [test_task_acceptance_review.py](../../../tests/test_task_acceptance_review.py), [test_task_tools.py](../../../tests/test_task_tools.py), [test_task_todo.py](../../../tests/test_task_todo.py) |
| Phase and evaluator authority | [phase_runner.py](../../../src/neurath/_assets/scripts/skill_harness/phase_runner.py), [adaptive_control_authority.py](../../../src/neurath/_assets/scripts/agent_harness/adaptive_control_authority.py), [evaluation_loop.py](../../../src/neurath/_assets/scripts/agent_harness/evaluation_loop.py), [test_phase_runner.py](../../../tests/runtime/skill_harness/test_phase_runner.py), [test_adaptive_control_authority.py](../../../tests/runtime/agent_harness/test_adaptive_control_authority.py) |
| Named API and discovery | [task_schema.py](../../../src/neurath/runtime/task_schema.py), [tasks.py](../../../src/neurath/runtime/tasks.py), `src/neurath/runtime/*_tasks.py`, [mcp.py](../../../src/neurath/agents/mcp.py), [mcp_guidance.py](../../../src/neurath/install/mcp_guidance.py), [test_communication_mcp.py](../../../tests/test_communication_mcp.py), [test_mcp_guidance.py](../../../tests/test_mcp_guidance.py) |
| Model and provider execution | [model_planning.py](../../../src/neurath/providers/model_planning.py), [permission_inheritance.py](../../../src/neurath/providers/permission_inheritance.py), [jobs.py](../../../src/neurath/providers/jobs.py), [job_recovery.py](../../../src/neurath/providers/job_recovery.py), [supervision.py](../../../src/neurath/providers/supervision.py), [provider_execution.py](../../../src/neurath/runtime/provider_execution.py), [provider_policy.py](../../../src/neurath/runtime/provider_policy.py), [test_model_planning.py](../../../tests/test_model_planning.py), [test_inherited_provider_modes.py](../../../tests/test_inherited_provider_modes.py), [test_provider_jobs.py](../../../tests/test_provider_jobs.py) |
| Durable messages and delivery | [store.py](../../../src/neurath/agents/store.py), [lifecycle.py](../../../src/neurath/agents/lifecycle.py), [delivery.py](../../../src/neurath/agents/delivery.py), [delivery_recovery.py](../../../src/neurath/agents/delivery_recovery.py), [newsroom.py](../../../src/neurath/agents/newsroom.py), [test_delivery_recovery.py](../../../tests/test_delivery_recovery.py), [test_newsroom_mcp.py](../../../tests/test_newsroom_mcp.py) |
| Memory, enclave and learning | [store.py](../../../src/neurath/memory/store.py), [hooks.py](../../../src/neurath/memory/hooks.py), [transcript.py](../../../src/neurath/memory/transcript.py), [learning.py](../../../src/neurath/memory/learning.py), [enclave_store.py](../../../src/neurath/_assets/scripts/agent_harness/enclave_store.py), [test_project_memory.py](../../../tests/test_project_memory.py), [test_learning.py](../../../tests/test_learning.py), [test_enclave_store.py](../../../tests/runtime/agent_harness/test_enclave_store.py) |
| Updates and reporting | [updates.py](../../../src/neurath/updates.py), [release_install.py](../../../src/neurath/release_install.py), [reporting.py](../../../src/neurath/reporting.py), [user_choices.py](../../../src/neurath/runtime/user_choices.py), [test_user_choices_mcp.py](../../../tests/test_user_choices_mcp.py), [test_reporting.py](../../../tests/test_reporting.py) |

Compatibility inspection still matters when a saved caller uses the retained material or registered-check path: [material_action.py](../../../src/neurath/_assets/scripts/agent_harness/material_action.py), [verification.py](../../../src/neurath/runtime/verification.py) and [material action regressions](../../../tests/runtime/agent_harness/test_material_action.py). A native check does not automatically produce a receipt from those compatibility paths.

## Validate changes to this map

For catalog, package and link behavior, run the publication regression first. Run the required full check on the final source when applicable:

```sh
uv run --locked pytest -q tests/test_publication.py
uv run --locked python tools/check.py
```

An execution-asset change additionally requires manifest regeneration, build and self-install update as described in [development](index.md). Prose-only changes do not by themselves require installation. Keep source integrity, package behavior, installed placement and native activation as separate observations when reporting the result.

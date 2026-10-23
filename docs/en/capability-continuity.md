# Capability disposition and replacement paths

[Public interfaces](interfaces.md) · [Specification](specification.md) · [Acceptance](acceptance.md) · [한국어](../ko/capability-continuity.md)

The 128 operations and 33 skills below are a **historical capability audit inventory**, not a new public list. Select 14 skills and 19 CLI commands. Preserve purpose and B outcome contracts, not historical names/counts/exposure. Baseline: capability documents at Git `e4bcc85`, later names, and current user corrections; not instructions to copy old code.

## 1. Destinations of 128 historical operations

| Previous name | Replacement path | Exposure | Reason | Outcome |
| --- | --- | --- | --- | --- |
| `harness_bypass` | maintenance CLI | internal/config/CLI | Maintenance CLI recovery available even during CLI/runtime failure | B01 |
| `session_status` | get-context | CLI | Consolidate overlapping current-execution reads | B02 |
| `session_inspect` | get-context | CLI | Consolidate overlapping current-execution reads | B02 |
| `turn_inspect` | get-context | CLI | Consolidate overlapping current-execution reads | B02 |
| `worktree_inspect` | get-context | CLI | Consolidate overlapping current-execution reads | B02 |
| `worktree_claim` | runtime writer lifecycle | internal | Coordinate/release on actual writer lifecycle; no model-assembled lease credentials | B03 |
| `worktree_release` | runtime writer lifecycle | internal | Coordinate/release on actual writer lifecycle; no model-assembled lease credentials | B03 |
| `worktree_isolation` | host worktree / Git / filesystem | host | Host tools handle checkout/preservation/cleanup; Neurath handles contention internally | B03 |
| `worktree_cleanup` | host worktree / Git / filesystem | host | Host tools handle checkout/preservation/cleanup; Neurath handles contention internally | B03 |
| `task_define` | create-task | CLI | Original-backed task definition | B04 |
| `task_list` | get-context | CLI | Read tasks and assignments in one ledger | B04 |
| `task_start` | update-task | CLI | Consolidate role-checked start/accept transitions | B04 |
| `task_resolve` | report-result | CLI | Consume reviews in current task/phase outcome checks; no separate completion vote | B04 |
| `phase_start` | start-workflow | CLI | Start a selected procedure/review loop as one run | B05 |
| `phase_current` | get-context | CLI | Read procedure/attempt/criteria/iteration history together | B05 |
| `phase_evidence_prepare` | workflow validation and evidence binding | internal | Runner validates inputs and binds evidence | B05 |
| `phase_complete` | report-result | CLI | Apply actual phase/round results to current attempt | B05 |
| `phase_finalize` | workflow finalization | internal | Finalize together with the last applicable result | B05 |
| `adaptive_read` | get-context | CLI | Read procedure/attempt/criteria/iteration history together | B06 |
| `adaptive_preflight` | workflow validation and evidence binding | internal | Runner validates inputs and binds evidence | B06 |
| `adaptive_replace` | revise-workflow | CLI | Unify justified method/scope revisions without authority to rewrite originals | B06 |
| `adaptive_override_goal` | revise-workflow | CLI | Unify justified method/scope revisions without authority to rewrite originals | B06 |
| `turn_yield` | host turn lifecycle / Stop | internal | No agent-issued termination-exception permission | B06 |
| `delegation_prepare` | assignment validation | internal | Validate recipient/scope/review conditions during assignment | B07 |
| `delegation_assign` | delegate-task | CLI | Unify actual work/review assignment | B07 |
| `evaluation_prepare` | assignment validation | internal | Validate recipient/scope/review conditions during assignment | B08 |
| `evaluation_read` | get-context | CLI | Read procedure/attempt/criteria/iteration history together | B08 |
| `evaluation_execute` | host execution tools | host | Host executes checks; Neurath observes attempts/results | B08 |
| `evaluation_report` | report-result | CLI | Attributed executor/reviewer reports | B08 |
| `evaluation_consume` | report-result | CLI | Consume reviews in current task/phase outcome checks; no separate completion vote | B08 |
| `evaluation_loop_open` | start-workflow | CLI | Start a selected procedure/review loop as one run | B09 |
| `evaluation_loop_read` | get-context | CLI | Read procedure/attempt/criteria/iteration history together | B09 |
| `evaluation_loop_round` | report-result | CLI | Apply actual phase/round results to current attempt | B09 |
| `evaluation_loop_close` | workflow finalization | internal | Finalize together with the last applicable result | B09 |
| `review_begin` | delegate-task | CLI | Unify actual work/review assignment | B10 |
| `review_report` | report-result | CLI | Attributed executor/reviewer reports | B10 |
| `review_consume` | report-result | CLI | Consume reviews in current task/phase outcome checks; no separate completion vote | B10 |
| `review_abort` | update-task | CLI | Cancel assignment while retaining outcomes/history | B10 |
| `review_publish` | host GitHub / review tools | host | Use existing tools for remote review/comment publication and retrieval | B10 |
| `review_comments` | host GitHub / review tools | host | Use existing tools for remote review/comment publication and retrieval | B10 |
| `provider_models` | get-context | CLI | Return models and supported policies together | B11 |
| `provider_plan` | provider validation and routing | internal | Validate/store settings/routes within delegate-task; preparation is not execution | B11 |
| `provider_plan_read` | get-context | CLI | Read pinned plan and actual execution state together | B11 |
| `provider_capabilities` | get-context | CLI | Return models and supported policies together | B11 |
| `provider_route` | provider validation and routing | internal | Validate/store settings/routes within delegate-task; preparation is not execution | B11 |
| `provider_run` | delegate-task | CLI | Entrypoint for actual supported-provider execution | B12 |
| `provider_status` | get-context | CLI | Read pinned plan and actual execution state together | B12 |
| `provider_cancel` | update-task | CLI | Actual target-run interruption | B12 |
| `provider_recover` | provider recovery | internal | Reconcile original run on reconnect; explicit repair uses memory resume | B12 |
| `collaboration_register` | peer connection lifecycle | internal | Register/update using actual connection identity/address | B13 |
| `collaboration_discover` | get-context | CLI | One peer inventory | B13 |
| `collaboration_inbox` | get-context | CLI | Read messages/conversation/actual delivery status together | B13 |
| `collaboration_send` | send-message | CLI | Same send operation with recipient/subscriber/reply references | B14 |
| `collaboration_reply` | send-message | CLI | Same send operation with recipient/subscriber/reply references | B13 |
| `collaboration_message` | read-message | CLI | Read selected full message | B13 |
| `collaboration_ack` | message transport and receipt | internal | Reads/transport outcomes produce receipts; adapters recover actual failures finitely | B13 |
| `collaboration_forward` | message transport and receipt | internal | Reads/transport outcomes produce receipts; adapters recover actual failures finitely | B14 |
| `collaboration_submitted` | message transport and receipt | internal | Reads/transport outcomes produce receipts; adapters recover actual failures finitely | B14 |
| `collaboration_assign` | delegate-task | CLI | Unify actual work/review assignment | B15 |
| `collaboration_accept` | update-task | CLI | Consolidate role-checked start/accept transitions | B15 |
| `collaboration_report` | report-result | CLI | Attributed executor/reviewer reports | B15 |
| `collaboration_task` | get-context | CLI | Read tasks and assignments in one ledger | B15 |
| `collaboration_conversation` | get-context | CLI | Read messages/conversation/actual delivery status together | B16 |
| `collaboration_close` | project notification settings / lifecycle | internal/config/CLI | Project notification settings through host tools and internal lifecycle | B16 |
| `collaboration_subscribe` | project notification settings | internal/config/CLI | Project notification settings through host tools and internal lifecycle | B16 |
| `collaboration_unsubscribe` | project notification settings | internal/config/CLI | Project notification settings through host tools and internal lifecycle | B16 |
| `collaboration_publish` | send-message | CLI | Same send operation with recipient/subscriber/reply references | B16 |
| `delivery_status` | get-context | CLI | Read messages/conversation/actual delivery status together | B14 |
| `delivery_redrive` | message transport and receipt | internal | Reads/transport outcomes produce receipts; adapters recover actual failures finitely | B14 |
| `newsroom_headlines` | list-articles | CLI | Read headlines/revisions | B17 |
| `newsroom_read` | read-article | CLI | Read body/comments | B17 |
| `newsroom_publish` | publish-article | CLI | Publish article | B17 |
| `newsroom_revise` | revise-article | CLI | Revision-checked article update | B17 |
| `newsroom_comment` | comment-on-article | CLI | Comment on article revision | B17 |
| `newsroom_peers` | get-context | CLI | One peer inventory | B17 |
| `newsroom_seen` | article read receipt | internal | Record actual full-read delivery, not an agent assertion | B17 |
| `artifact_put` | host artifact tools + internal reference ingestion | host+internal | Use host artifact storage; preserve references in reports/checkpoints | B18 |
| `artifact_read` | memory read / host artifact tools | CLI+host | memory read resolves Neurath records; host tools read original files | B18 |
| `memory_recall` | memory search / memory read | CLI | Filter history/lessons by type/state, then read details | B18 |
| `memory_checkpoint` | memory checkpoint | CLI | Saving a report needs no separate skill | B18 |
| `memory_pull` | memory search / memory read / memory resume | CLI | Separate discovery/preview from adoption effects | B18 |
| `enclave_read` | get-context | CLI | Distinct fact read/update/delete | B19 |
| `enclave_set` | memory update | CLI | Distinct fact read/update/delete | B19 |
| `enclave_delete` | memory update | CLI | Distinct fact read/update/delete | B19 |
| `learning_status` | memory search / memory read | CLI | Filter history/lessons by type/state, then read details | B20 |
| `learning_pending` | memory search / memory read | CLI | Filter history/lessons by type/state, then read details | B20 |
| `learning_history` | memory search / memory read | CLI | Filter history/lessons by type/state, then read details | B20 |
| `learning_defer` | reflection / versioned lesson source | internal/config/CLI | Apply deferral/retraction through attributed lesson sources and reflection lifecycle | B20 |
| `diagnostics_integrity` | get-context / maintenance CLI | CLI | One diagnosis interface with scoped inputs | B21 |
| `diagnostics_project` | get-context / maintenance CLI | CLI | One diagnosis interface with scoped inputs | B21 |
| `diagnostics_profile` | get-context / maintenance CLI | CLI | One diagnosis interface with scoped inputs | B21 |
| `diagnostics_continuation` | get-context / maintenance CLI | CLI | One diagnosis interface with scoped inputs | B21 |
| `incident_record` | incident / observation lifecycle | internal | Derive records from actual fault/execution/recovery events; no arbitrary success-setting tool | B22 |
| `incident_validate` | get-context / maintenance CLI | CLI | One diagnosis interface with scoped inputs | B22 |
| `incident_resolve` | incident / observation lifecycle | internal | Derive records from actual fault/execution/recovery events; no arbitrary success-setting tool | B22 |
| `incident_escalate` | incident / observation lifecycle | internal | Derive records from actual fault/execution/recovery events; no arbitrary success-setting tool | B22 |
| `incident_refresh` | incident / observation lifecycle | internal | Derive records from actual fault/execution/recovery events; no arbitrary success-setting tool | B22 |
| `incident_supersede` | incident / observation lifecycle | internal | Derive records from actual fault/execution/recovery events; no arbitrary success-setting tool | B22 |
| `process_evidence_record` | incident / observation lifecycle | internal | Derive records from actual fault/execution/recovery events; no arbitrary success-setting tool | B22 |
| `monitor_start` | task dependency lifecycle | internal/config/CLI | Start internal observation from an actually requested external task dependency | B23 |
| `monitor_status` | get-context | CLI | Read monitoring/events/actual state together | B23 |
| `monitor_cancel` | update-task | CLI | Explicit monitoring cancellation | B23 |
| `monitor_recover` | monitor lifecycle | internal | Process consumption/wait/recovery/handoff from work/host events | B23 |
| `monitor_readback` | get-context | CLI | Read monitoring/events/actual state together | B23 |
| `monitor_event` | get-context | CLI | Read monitoring/events/actual state together | B24 |
| `monitor_ack` | monitor lifecycle | internal | Process consumption/wait/recovery/handoff from work/host events | B24 |
| `monitor_external_wait` | monitor lifecycle | internal | Process consumption/wait/recovery/handoff from work/host events | B24 |
| `monitor_handoff` | monitor lifecycle | internal | Process consumption/wait/recovery/handoff from work/host events | B24 |
| `installation_plan` | maintenance CLI + update-neurath / memory resume | CLI+skill | Self-update/recovery works outside the failed business-command path; remove extra consent-object APIs | B25 |
| `installation_apply` | maintenance CLI + update-neurath / memory resume | CLI+skill | Self-update/recovery works outside the failed business-command path; remove extra consent-object APIs | B25 |
| `installation_recover` | maintenance CLI + update-neurath / memory resume | CLI+skill | Self-update/recovery works outside the failed business-command path; remove extra consent-object APIs | B25 |
| `releases_status` | maintenance CLI + update-neurath / memory resume | CLI+skill | Self-update/recovery works outside the failed business-command path; remove extra consent-object APIs | B26 |
| `releases_check` | maintenance CLI + update-neurath / memory resume | CLI+skill | Self-update/recovery works outside the failed business-command path; remove extra consent-object APIs | B26 |
| `releases_notice` | maintenance CLI + update-neurath / memory resume | CLI+skill | Self-update/recovery works outside the failed business-command path; remove extra consent-object APIs | B26 |
| `releases_prepare` | maintenance CLI + update-neurath / memory resume | CLI+skill | Self-update/recovery works outside the failed business-command path; remove extra consent-object APIs | B26 |
| `releases_choose` | maintenance CLI + update-neurath / memory resume | CLI+skill | Self-update/recovery works outside the failed business-command path; remove extra consent-object APIs | B26 |
| `releases_apply` | maintenance CLI + update-neurath / memory resume | CLI+skill | Self-update/recovery works outside the failed business-command path; remove extra consent-object APIs | B26 |
| `releases_recover` | maintenance CLI + update-neurath / memory resume | CLI+skill | Self-update/recovery works outside the failed business-command path; remove extra consent-object APIs | B26 |
| `maintenance_choice_read` | maintenance CLI + update-neurath / memory resume | CLI+skill | Self-update/recovery works outside the failed business-command path; remove extra consent-object APIs | B26 |
| `maintenance_choice_prepare` | maintenance CLI + update-neurath / memory resume | CLI+skill | Self-update/recovery works outside the failed business-command path; remove extra consent-object APIs | B26 |
| `reporting_status` | host artifact / GitHub tools | host | Use existing artifact/publication tools and actual user authority; no dedicated publication/approval ledger | B27 |
| `reporting_list` | host artifact / GitHub tools | host | Use existing artifact/publication tools and actual user authority; no dedicated publication/approval ledger | B27 |
| `reporting_read` | host artifact / GitHub tools | host | Use existing artifact/publication tools and actual user authority; no dedicated publication/approval ledger | B27 |
| `reporting_prepare` | host artifact / GitHub tools | host | Use existing artifact/publication tools and actual user authority; no dedicated publication/approval ledger | B27 |
| `reporting_consent` | host artifact / GitHub tools | host | Use existing artifact/publication tools and actual user authority; no dedicated publication/approval ledger | B27 |
| `reporting_approve` | host artifact / GitHub tools | host | Use existing artifact/publication tools and actual user authority; no dedicated publication/approval ledger | B27 |
| `reporting_submit` | host artifact / GitHub tools | host | Use existing artifact/publication tools and actual user authority; no dedicated publication/approval ledger | B27 |
| `reporting_reconcile` | host artifact / GitHub tools | host | Use existing artifact/publication tools and actual user authority; no dedicated publication/approval ledger | B27 |

## 2. Destinations of 33 historical skills

| Previous skill | Decision | Replacement | Reason | Retained outcome |
| --- | --- | --- | --- | --- |
| `review-spec` | skill | review-spec | Reusable procedure with decisions and verification | Report requirement/design/implementation gaps and evidence; preimplementation audit is not implementation acceptance. |
| `qa` | skill | qa | Reusable procedure with decisions and verification | Reproduce specified UI/API/persistence scenarios; distinguish failure and untested behavior. |
| `autopilot` | skill | autopilot | Reusable procedure with decisions and verification | Complete requested issues/dependencies without inventing unrelated work. |
| `checkpoint` | CLI | memory checkpoint | No separate skill for one report save | Preserve originals/current outcomes/remaining work/next steps in a resumable report. |
| `commit` | host/project | host tools / selected project skill | Ordinary agent work or project-specific expertise, not an installed Neurath default | Match diff/checks, commit authorized files only, verify actual SHA. |
| `create-pr` | host/project | host tools / selected project skill | Ordinary agent work or project-specific expertise, not an installed Neurath default | Create a scoped PR reflecting branch/diff/validation and verify remote identity/body. |
| `create-issue` | host/project | host tools / selected project skill | Ordinary agent work or project-specific expertise, not an installed Neurath default | Create an issue retaining original requirements/acceptance/dependencies and verify publication. |
| `create-worktree` | host/project | host tools / selected project skill | Ordinary agent work or project-specific expertise, not an installed Neurath default | Create an isolated checkout from requested Git state while preserving original work/uncommitted files. |
| `audit-deps` | external/project | project dependency tooling / selected specialist skill | Useful specialist work, not a Neurath first-party default | Report risks/licenses/update candidates against manifests/locks and evidence without implicit updates. |
| `test-harness` | internal/development | harness tests and internal improvement validation | Validation/improvement for Neurath development or user-requested reflection, not a default user skill | Record scenario events/verdicts/failures and distinguish fixture/native validation. |
| `explain-code` | host/project | host tools / selected project skill | Ordinary agent work or project-specific expertise, not an installed Neurath default | Explain actual code paths with sources; do not assert unsupported behavior. |
| `design-ui` | skill | design-ui | Reusable procedure with decisions and verification | Propose directions/behavior without treating proposals as adopted designs. |
| `finish-session` | skill | finish-session | Reusable procedure with decisions and verification | Verify remaining requirements/procedure/checks and scoped Git/graph/handoff/ownership; disclose unfinished work. |
| `graphify` | external | existing Graphify skill / CLI | Reuse the dedicated capability rather than duplicating it | Query/update requested source/document relationships and check semantic retention. |
| `implement-ui` | merge | implement-spec | UI-specific references and checks within the same implementation procedure | Implement/verify selected visuals/interactions without substituting another design. |
| `debug` | skill | debug | Reusable procedure with decisions and verification | Connect reproduced failure, cause, fix, and regression result. |
| `watch-pr` | CLI | task dependency lifecycle / get-context / update-task | Registration is a tool; waiting/resumption belongs to runtime | Notify meaningful changes of the specified PR and clean up after cancellation/completion. |
| `optimize-harness` | internal/development | internal reflection and improvement evaluation | Validation/improvement for Neurath development or user-requested reflection, not a default user skill | Compare improvement effect, healthy controls and cost; retract regressions. |
| `plan` | merge | define-spec | Execution planning belongs in the specification, not a separate mandatory skill | Define actionable scope/order/dependencies/validation without claiming execution. |
| `review-pr` | merge | review-code | A PR identifies the code-review target, not a separate review procedure | Report actionable findings for exact PR HEAD/requirements; stale review cannot pass. |
| `implement-issue` | merge | implement-spec | Implement specifications/requests without requiring an issue | Implement issue requirements and assess acceptance using relevant validation/artifacts. |
| `memory-to-rules` | internal+host | learning lifecycle / host file editing | Validation/improvement for Neurath development or user-requested reflection, not a default user skill | Propose/apply relevant rules from verified lessons without rewriting user instructions. |
| `review-code` | skill | review-code | Reusable procedure with decisions and verification | Report concrete defects/locations/impact without elevating preferences into requirements. |
| `review-ui` | skill | review-ui | Reusable procedure with decisions and verification | Compare actual UI/interactions to criteria; screenshots alone cannot establish behavior. |
| `sync-design` | skill | sync-design | Reusable procedure with decisions and verification | Compare adopted design/implementation and synchronize affected scope only. |
| `dev-docs` | merge | sync-docs | Keep audience-specific guidance within one documentation workflow | Write contributor docs matching actual development/extension/validation and check examples/links. |
| `sync-docs` | skill | sync-docs | Reusable procedure with decisions and verification | Synchronize languages/related pages without inconsistent facts or stale guidance. |
| `user-docs` | merge | sync-docs | Keep audience-specific guidance within one documentation workflow | Explain user goals/workflows/actual limits without claiming unsupported behavior. |
| `pr-feedback` | skill | pr-feedback | Reusable procedure with decisions and verification | Assess feedback against current changes, apply/verify/respond where justified, separate unrelated demands. |
| `update-deps` | external/project | project dependency tooling / selected specialist skill | Useful specialist work, not a Neurath first-party default | Verify scoped manifest/lock updates, compatibility checks and regression outcomes. |
| `update-status` | host/project | host tools / selected project skill | Ordinary agent work or project-specific expertise, not an installed Neurath default | Reflect evidenced progress/remaining work without inflated completion. |
| `update-neurath` | skill | update-neurath | Reusable procedure with decisions and verification | Verify requested distribution, installation/data preservation and live new connection; expose migration failures. |
| `reconnect-host` | CLI/internal | memory resume / runtime recovery; maintenance CLI when CLI is unavailable | Use existing memory resume and runtime recovery; CLI fallback during CLI/runtime failure | Restore actual connection through official paths and resume original work; another process is not the existing connection. |

## 3. Capability-specific observable outcomes

B entries define the mapped operation outcomes. A39 must exercise each replacement execution path against these outcomes; family names or a shared passing test do not establish coverage. These are not new approval procedures.

| ID | Observable contract |
| --- | --- |
| B01 | Reading does not mutate; bypass disables harness gates only; restoration rechecks an actual gated path without changing host permissions. |
| B02 | Each read returns the actual target, execution/connection/writer state and uncertainty without acquiring ownership or invoking inference. |
| B03 | Concurrent claims allow one writer; stale release cannot release the current lease. Isolation checks designated relationships. Cleanup preserves unmerged commits, dirty/untracked and needed ignored data; removal requires verified recovery. |
| B04 | Definition/start match originals/current revisions; full list and TODO agree. Resolution retains actual outcomes and outstanding follow-up; stale outcomes cannot close new requirements. |
| B05 | Start pins the selected definition; current returns execution conditions; preparing evidence is not execution; matching attempt outcomes advance/finalize once. |
| B06 | Read/preflight do not execute or change scope. Method changes retain prior state/reason; goal changes follow actual corrections. Yield preserves actual completion/wait/interruption reasons. |
| B07 | Distinguish preparation from actual assignment; bind recipient, instruction revision and scope; expose propagated corrections/cancellation and unconfirmed delivery. |
| B08 | Read conditions/target/role, actually execute evaluation, report the evaluated candidate, and consume only against its current applicability; failed/stale evaluations cannot pass. |
| B09 | Open with original goal/criteria, retain each round change/finding/outcome; read does not execute; close distinguishes resolved/unresolved and bounds stagnation. |
| B10 | Bind reviewer/target/scope; distinguish consumption and publication. Abort is not a pass; publish/read applicable results/comments for the current PR within authorized scope. |
| B11 | Inspect actual models/capabilities/routes; persist/read explicit model/policy plans without silently substituting unsupported routes or executing on a read. |
| B12 | Execute the confirmed plan; distinguish submission/outcome in status; confirm cancellation; recovery reconciles the existing run without duplicate start or resurrecting cancelled work. |
| B13 | Retain actual peer address/author; distinguish inbox summary and full body; replies retain conversation; ACK refers to read messages, not work acceptance/completion. |
| B14 | Read original message/recipient delivery data and record submission. Status never resends; redrive repairs a confirmed failure for the same message; late delivery cannot regress a newer ACK. |
| B15 | Distinguish assignment/acceptance/progress/completion; recipients execute assigned work without another human prompt; task reads show current-revision outcomes/remaining work. |
| B16 | Conversation read/close preserves history/unfinished work; subscribe/unsubscribe changes publication recipients without waking unrelated peers. |
| B17 | Selective headlines/body; notify active peers only; reject revision conflict and retain old body; comments bind the read revision; peers reflect activity; seen marks that event, not later revisions. |
| B18 | Artifact round-trip retains content/provenance/size bounds; recall selects history; checkpoint is a report; pull preview preserves ownership and adoption verifies old-writer stop and actual resumption. |
| B19 | Set/read/delete share fact revisions; reject stale set/delete; retain deletion history without deleting original requirements/tasks; large content keeps retrievable references. |
| B20 | Generate/apply new lessons within a user-requested retrospective. Distinguish applied/pending/historical effects; defer preserves reason and unapplied state rather than promoting success; subsequent failures inform retraction. |
| B21 | Diagnose integrity/project connection/profile/continuation separately with reproducible causes; missing data/failures are not healthy emptiness; diagnostics do not overwrite settings. |
| B22 | Record symptoms and actual evidence; resolve through reproduction/fix/regression checks. Escalation retains unresolved transfer, refresh reobserves, supersession links the prior incident without deleting history/inventing success. |
| B23 | Monitor original scope and expose first observation/actual target state; cancellation stops new notifications/actions; recovery checks current cancellation/owner; unchanged state never wakes inference. |
| B24 | Read/consume exact events without equating ACK and resolution; waiting retains release conditions; handoff transfers/stops resources and retains pending events/remainder without duplicate monitors. |
| B25 | Plans bind owned configuration before/after and distribution; apply preserves user configuration and verifies writer cutover; recovery retains new records and verifies reads/resumption. |
| B26 | Distinguish official release observation/notice/preparation/selection/application; previously authorized updates require no redundant selection. Necessary choices bind intent/target/scope; activation requires new host evidence and recovery preserves new data. |
| B27 | Reading/preparing private drafts does not publish. Match actual user authority to content/destination without redundant consent; reconcile uncertain submission remotely and retain original work on reporting failure. |

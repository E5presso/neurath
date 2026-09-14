<!-- date: 2026-09-14; synced_from: 655c8768709e59b5e5012bab0adc4d888e3e7fa5 + current working-tree facts -->

[한국어](../../ko/contributing/runtime-lifecycle.md)

# Runtime state from admission to recovery

A model turn, a host process, a registered task and a worktree lease can end at different times. Neurath records each lifetime explicitly so that interruption does not erase work and process exit does not silently release ownership.

## The state objects

| Object | States or identity | Meaning |
| --- | --- | --- |
| Session | `active`, `ended` | Durable native-session domain record. Explicit `ended` is terminal. |
| Participant | `root`, `subagent`; `active`, `idle`, `stopped`, `retired` | Who participates and whether new work may be assigned. |
| Native lineage | `unattested`, `host-attested` | Whether the host established the claimed immediate parent relationship. |
| Foreground turn | `active`, `ready-to-stop`, `closed` | Current participant control of a request. |
| Turn outcome | `completed`, `awaiting-input`, `failed`, `incomplete` | Reason control returns, subject to the applicable completion contract. |
| Task | `pending`, `in_progress`, `succeeded`, `failed`, `invalidated` | Requested work and its owner-reported outcome. |
| Explicit workflow | `active`, `completed`, `failed` | A contracted sequence with its own phases and evidence. |
| Delegation | `pending`, `reported`, `consumed`, `cancelled` | Assignment delivery and the required owner's consumption. |
| Worktree claim | owner, `lease_epoch`, `fencing_token`; `active` or `cleanup-reserved` | Current writer authority and its generation. |

The session kernel applies transitions; the state handle binds caller access; the registry controls worktree mutation. An identifier in a request does not create any of these relationships.

## Start, work and Stop

Native session-start and prompt events establish the caller and current instruction. The root can then register tasks and retain their source receipts. Every task mutation requires the active native root owner and an active foreground turn. A recognized participant may read the list under the read admission rules.

The owner starts pending work and records a terminal outcome with exact list and task revisions. Both starting a task and resolving it as `succeeded` require its dependencies to be terminal. A failed or invalidated outcome can still be recorded while dependencies are unresolved. Terminal dependency means settled; it does not imply every dependency succeeded. Acceptance conditions determine what the dependent result can honestly claim.

When a task list exists, Stop reads its latest version and closes the root turn in one transaction. All registered tasks must be terminal. A native TODO update, checkpoint or extra workflow report does not provide another completion vote. A session without a registered task list retains its legacy completion rules; absence of a list is not evidence that requested work was done.

A normal Stop keeps requesting continuation while completion remains unresolved. Repeatedly issuing Stop does not resolve a pending task. An agent-created question and its delivery acknowledgement are not user approval to suspend or reduce the original work. The original tasks and their completion requirements remain in force.

## Return attention to the original task

[Goal reminders](../../../src/neurath/runtime/goal_reminders.py) add bounded context on `UserPromptSubmit`, `PostToolUse`, or `PostToolUseFailure` for a verified, participating native root. With non-successful task records, delivery occurs on the first eligible event, a changed prompt source, 12 distinct completed `tool_use_id` values, or the next eligible new event after 300 seconds. Success and failure callbacks for one invocation count once. There is no background timer that wakes a session after five minutes.

Each distinct authenticated `PreToolUse` invocation of `task_define`, `task_start` or `task_resolve` also receives decision context without postponing the periodic cadence. Tool descriptions guide the choice before invocation. The selected task is shown first when available.

The addition is at most 2,400 UTF-8 bytes and contains up to four task excerpts, preferring active work before terminal unsuccessful results. Existing additional context is retained. Periodic delivery skips empty or all-successful lists. Task-decision delivery also covers those lists, including the first definition. Child or foreign identities and migrated source sessions receive neither form.

The existing SQLite stores cadence and the most recent 64 event keys for duplicate suppression. The reminder does not change task definitions, revisions, outcomes, claims, or permissions. It asks the agent to register necessary follow-up progressively after judging relevance, existing evidence and scope; it requests no separate reflection report, review or completion gate. [Reminder tests](../../../tests/test_goal_reminders.py) cover cadence, size, identity, deduplication, and state preservation; the quality of the agent's resulting judgment is not mechanically certified.

## Own the worktree for the relevant lifetime

Read `worktree_inspect` or the ownership portion of `session_status` before mutation. `worktree_claim` obtains the claim for the actual current identity. Retain the returned epoch and token and pass them unchanged to `worktree_release` as `expected_lease_epoch` and `fencing_token`.

A new claim or supported handoff changes the ownership generation. Old tokens then fail even if the same filesystem path still exists. Cleanup reserves the exact lease before destructive Git operations; normal mutation, handoff and release are rejected while the reservation is active. Cleanup requires verified `base_branch` and `remote_ref` rather than guessed repository conventions.

A host process ending or a model becoming idle does not transfer the claim. A checkpoint does not release it. Inspect the current lease before assuming ownership after resume, and follow the applicable finish or cleanup workflow for release.

## Resume without rewriting history

The host's `SessionEnd` closes a connection while preserving resumable session state, tasks, enclave and ownership. A verified native resume reopens participation in that same session. The explicit kernel event `SessionEnded` permanently terminates a domain session and is not automatically reversible.

On a verified interruption and resume, only the previous known foreground turn may be closed. Pending tasks and delegations remain. A late Stop cannot close the new turn; unmatched events produce diagnostics without changing unrelated state. An app peer delivery that lacks a prompt event needs transcript and native-turn evidence to continue the existing goal, and cannot create approval for new work.

After interruption, read the relevant object rather than reconstructing state from conversational summaries: `task_list` for requested work, `phase_current` for an explicit workflow, `worktree_inspect` for ownership and the appropriate delivery or provider diagnostic for an execution problem.

## Explicit phases and independent evaluation

A contracted skill begins with `phase_start`; `phase_current` exposes its current phase and revision. For an adaptive workflow, actual independent evaluator authority must exist before initialization. Preparing a candidate binds its goal, intent, source and workflow revisions together with a content digest.

The evaluator must read that exact candidate and its evidence. Findings lead to a revised candidate and a new evaluation. The parent validates and consumes the authentic report. A useful peer-provider report does not acquire direct-child evaluation authority merely by calling itself independent.

`phase_evidence_prepare` validates current labels and revision, then registers an immutable evidence reference. Git observations and agent reports have different assurance. Supply those returned references to `phase_complete`; an arbitrary artifact string does not satisfy the phase contract. Changed source, owner or workflow invalidates reuse.

For operational final phases, `phase_complete` may accept `terminal_state` and complete the phase and workflow atomically. Do not then finalize it again. Contracts that require a separate authority transition retain `phase_finalize`. The fixed review family—`review_begin`, `review_report`, `review_consume`, `review_abort`—also retains its own matrix. `review_publish` must refer to the exact current pull-request head.

## Provider execution and result delivery

`provider_run` durably admits a run and promptly returns its ID. A detached worker uses an owned native connection to report start, waiting, failure, disconnect, cancellation or completion. The issuing agent remains responsible for the follow-up until accepted completion, cancellation or verified handoff, even when its model turn has ended.

There is no ordinary task-lifetime timeout. Individual connection, write and response deadlines still apply, and the event loop must accept messages and cancellation while native work is running. Use `provider_status` after an event or error to diagnose the run; completion is delivered through events rather than periodic status scans.

The issuer's connection stays available while issued work or unacknowledged obligations remain. Idle Codex can receive a new turn, while an active turn receives steering. Claude Code retains notifications until its current result and iterator finish; mid-stream input is not a separately acknowledged turn. Closing a connection preserves late notifications and lets already-started input writes finish.

Issuer death does not cancel authorized work in another instance. Recovery with `provider_recover(run_id, key)` requires the current issuer's recorded execution, proof of the prior worker generation and closure of its process and connection. A worker lease excludes competing recovery. Recovery restores the recorded native session, rechecks current policy and reconnects pending delivery without repeating the original assignment. Admission is reported separately from actual recovery completion. Powered-off-host or lost-disk execution recovery is not guaranteed.

## Messages and background monitors

Messages are durably committed before notification. `queued`, `submitted`, `received` and `replied` distinguish storage, host acceptance, recipient acknowledgement and response. The receiver reads the complete body before acknowledging; an ID-only notice is insufficient. An acknowledgement stops retries but does not accept or complete a task.

Uncertain sending and missing acknowledgements remain retryable with the same identity, content and key. Endpoint generations fence delayed old attempts. Timeouts do not silently erase accepted pending messages. Repair-required records retain their body and failure history; `delivery_redrive` validates the current revision and actual repaired transport before resuming delivery. See [collaboration](collaboration-contract.md).

Monitoring also separates admission from observation. `monitor_start` returns a run ID and grants one native launch bound to the actual process generation and code. `started` requires the first external observation and readback. `monitor_cancel` is a durable cancellation request; actual exit must still be observed. Recovery requires prior termination and the applicable leases. `monitor_ack`, `monitor_external_wait` and `monitor_handoff` preserve event consumption and waiting or retirement; observe-only monitoring does not resume its owner.

Before resuming the owner, the PR monitor reads the owner's latest native policy. If that policy cannot be observed or has changed, use `monitor_recover` to restore the supported path; resume arguments must not override permissions. See [monitor resume policy checks](../../../src/neurath/runtime/monitor_runtime.py).

## Move legacy state safely

The canonical store is `.neurath/local/runtime.sqlite3` under the Git-common-derived control root. Importing legacy state stages data; it does not retire old writers or activate new host adapters. A dormant linked worktree can still contain an old launcher, so every linked launcher matters.

The bootstrap cutover interface is reserved for inspecting and retiring those legacy writers:

```sh
neurath --root TARGET cutover inspect
neurath --root TARGET cutover prepare
neurath --root TARGET cutover apply --expected-token TOKEN_FROM_INSPECTION
neurath --root TARGET cutover recover
```

These are separate actions, not an unconditional command sequence. `inspect` compares the four declared SQLite sources, import guards and linked launchers. `prepare` imports only if the canonical database is absent. Stop the relevant writers before `apply`, then use the exact reviewed inspection token. The process requires Unix `lsof` and closed SQLite handles. Open handles or journals, changed guards, unknown launchers and unknown late rows block retirement.

Apply temporarily fences known generated launchers, privately backs up originals and replaces legacy SQLite paths with directory tombstones. It updates guards and audit state transactionally while preserving canonical data. New message bodies or recipients cause rejection; only supported lifecycle differences against terminal canonical records may be reconciled. Launchers are restored after the permanent path fence is established, and affected worktrees are listed for supported updates.

For an interrupted journal, `recover` restores paths before commit or completes launcher restoration after commit. Conflicting files and damaged backups are preserved and reported. Installation is blocked while a cutover journal remains. After updating affected worktrees, verify placement, protocol and actual native activation separately.

Implementation and checks are indexed in [capability map](capability-map.md). [Task tools](task-tools.md) specifies operation inputs; [host integration](hosts.md) covers the native evidence behind these transitions.

## Sources for design review

Use these implementation references to test whether a change preserves the responsibilities described above. Compatibility code is relevant only when reviewing a retained saved-call path.

| Responsibility | Source and regression reference |
| --- | --- |
| Goals, phases and evaluation | [adaptive_control_authority.py](../../../src/neurath/_assets/scripts/agent_harness/adaptive_control_authority.py), [phase_runner.py](../../../src/neurath/_assets/scripts/skill_harness/phase_runner.py), [task_ledger_tasks.py](../../../src/neurath/runtime/task_ledger_tasks.py), [workflow_tasks.py](../../../src/neurath/runtime/workflow_tasks.py) |
| Host and exact-call admission | [mcp.py](../../../src/neurath/agents/mcp.py), [hooks.py](../../../src/neurath/hosts/hooks.py), [identity.py](../../../src/neurath/hosts/identity.py) |
| Messages and provider lifetime | [delivery.py](../../../src/neurath/agents/delivery.py), [delivery_recovery.py](../../../src/neurath/agents/delivery_recovery.py), [newsroom.py](../../../src/neurath/agents/newsroom.py), [store.py](../../../src/neurath/agents/store.py), [jobs.py](../../../src/neurath/providers/jobs.py), [model_planning.py](../../../src/neurath/providers/model_planning.py), [supervision.py](../../../src/neurath/providers/supervision.py), [provider_execution.py](../../../src/neurath/runtime/provider_execution.py) |
| Bounded retained context | [hooks.py](../../../src/neurath/memory/hooks.py), [learning.py](../../../src/neurath/memory/learning.py), [transcript.py](../../../src/neurath/memory/transcript.py) |
| Preserving installation and user choices | [transaction.py](../../../src/neurath/install/transaction.py), [release_install.py](../../../src/neurath/release_install.py), [user_choices.py](../../../src/neurath/runtime/user_choices.py), [updates.py](../../../src/neurath/updates.py) |
| Saved-call compatibility | [verification.py](../../../src/neurath/runtime/verification.py) |

### Scheduled continuation

Codex scheduled messages use paired native `codex_app.automation_update` delivery records. Like peer delivery, reconciliation verifies the current root, turn, output ID, method name and output digest; it does not trust heartbeat markup or mint a user prompt receipt. An ordinary called-tool result, mismatched pair or unreconciled human prompt cannot reopen execution through this path. Existing instruction sources and task state continue to govern the work.

### App-created independent tasks

Codex app creation identifies an independent root with `thread_source="agent_created_thread"` and delivers its initial request through paired `codex_app.create_thread` records. The same root and delivery checks apply. Host metadata may classify accompanying context as `plugins.recommendations`, `agents_md.instructions`, or `environments.environment_context`; unknown or mixed user context is not skipped. Reconciliation enables the verified native turn without creating a human prompt receipt or inheriting the creator's authority. Substantive work still requires its authorized instruction or task-assignment scope.

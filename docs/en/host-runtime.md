# Host hooks and execution lifecycle

[Documentation](index.md) · [Task ledger](task-ledger.md) · [Phase execution](workflow-runner.md) · [한국어](../ko/host-runtime.md)

This is the request-scoped runtime library for #142. It does not modify installed Codex or Claude settings. The hook entry point uses spakky-typer. Management commands are documented in [recovery](recovery.md); remaining business CLI and installation wiring belong to #148 and #151.

## Execution and writing

`Execution` connects a registered host session with its actual `agent_id`; roots use an empty child ID. Independent provider roots remain separated by the existing session provider scope. The actual `SessionStart.source` is retained for startup, resume, fork and compaction. Neither that value nor a native ID is treated as permission evidence.

The adapter stores Codex `turn_id` and Claude `prompt_id` without inventing missing identifiers. Older hosts without a turn identifier can still read and diagnose, but mutation or stopping that requires a current turn yields as unconfirmed. A new message records its turn without automatically resuming cancelled or paused work. `ResumeExecutionUseCase` handles an actual resume instruction. Resuming does not confirm that an earlier write has ended.

`Writer` tracks a shared working folder's execution, turn, tool call and generation. Subdirectories of one Git working tree share a writer resource; distinct worktrees remain separate. Reads, diagnostics and child inspection need no writer lease. The current working-folder writer names are `Edit`, `Write`, `Bash`, `apply_patch` and `exec_command`. Additional working-folder writers must declare that effect. Worktree creation, removal and preservation remain host-tool responsibilities.

Existing SQLite write transactions and repository version checks serialize competing acquisitions. Redelivery of the same active call returns its generation; another call conflicts. Recovery using an old owner or generation cannot release the current writer.

## Hook contract

`neurath hook handle --provider codex` (or `--provider claude`) reads host JSON from stdin and writes one control JSON object to stdout. `HookCliController` is discovered through `@CliController`/`@command` and directly receives the async `ReceiveHookUseCase`. Session registration and hook processing share its `AsyncTransaction`. Contracts come from the [Codex hook schemas](https://github.com/openai/codex/blob/main/codex-rs/hooks/src/schema.rs) and [Claude hook documentation](https://code.claude.com/docs/en/hooks).

| Event | Behavior |
| --- | --- |
| `SessionStart`, `SubagentStart` | Retain the actual session/child connection and start source; do not clear pauses |
| `UserPromptSubmit` | Record the actual turn; duplicate delivery does not reverse cancellation |
| `PreToolUse` | Let reads proceed without leases; check execution state and writer ownership for writes |
| `PostToolUse`, `PostToolUseFailure` | Release only a confirmed terminal write with the same execution, turn and call; distinguish actual interruption |
| `Interrupt` | Record Codex's actual interruption event for its target turn |
| `StopFailure` | Pause on host failure while retaining unfinished work |
| `Stop`, `SubagentStop` | Decide continue, yield or allow from fresh applicable tasks and phase progress |
| `SessionEnd` | Record connection closure without inventing task success or write termination |

An allowed result `{}` preserves the native host permission flow. Unfinished executable work receives `decision:block` with TODO feedback. Repeating a Stop rejection without task or phase progress returns `continue:false` and `stopReason`. External waiting or a cancelled/paused execution also yields without recording success. Independent executable work takes priority over waiting. An empty TODO allows a conversation to end but is not proof of goal completion.

Stop does not launch an evaluator. #138 configures the independent outcome-evaluation phase; existing runner rules already prevent task success before required connected phases complete. Root TODOs are not automatically imposed on children. #144 will connect child tasks through actual assignments.

## Actual termination and uncertainty

Codex unified-exec normalizes shell tools to `Bash` and emits their `PostToolUse` only after the process terminates. Its string response proves only that lifecycle event, not success or complete reading: the output may be truncated or describe failure. See the [execution result implementation](https://github.com/openai/codex/blob/main/codex-rs/core/src/tools/context.rs).

Claude synchronous `Bash` responses use the `stdout`, `stderr` and `interrupted` contract. Background handles, running session IDs and unrecognized outcomes retain the lease. Recovering such executions requires actual terminal observation from the owning executor's `IWriterObserverService`. The included concrete `PosixWriterObserverService` supports POSIX process groups started directly by that executor with `Popen(start_new_session=True)`. It never takes over an external host by guessing a PID or terminates the entire host application.

`CancelExecutionUseCase` pauses further writes and records `ExecutionCancellationRequested`. `RecoverWriterUseCase` checks the current lease generation and records `WriterRecoveryRequested`. After commit, the event adapter invokes InterruptExecution or ObserveWriter. Those use cases observe the host outside DB locks and publish result events. The adapter maps each result to ConfirmCancellation or ReleaseWriter, which rechecks turn, owner and generation in a new transaction. The request response is not confirmation of termination or release; the latest persisted state is authoritative. Handler failure retains the paused execution or active lease.

Database and hook failures return `continue:false` with recovery guidance. Explicit `--bypass` suspends enforcement while retaining observable turns, cancellation, and termination. Database failure reports unverified bookkeeping and attempts an independent recovery record; bypass does not grant native permission. Returned TODO and `stopReason` are host-delivery content; producing JSON does not record that the user received a notification. Operational diagnostics and restoration verification are documented in [recovery](recovery.md); installation wiring belongs to #151.

## Persistence and verification

`core_0005` adds execution and writer tables. It does not infer active execution, approval or success from earlier sessions. Destructive downgrade is rejected when runtime history exists.

Regression tests exercise actual SQLite concurrency, restart, late outcomes, cancellation, explicit resume, child reads, phase progress, external waiting, database failures and bypass. Real processes verify targeted interruption and liveness. Passing these tests does not prove installation or activation in the user's host.

The default SQLite URL uses `sqlite+aiosqlite`. Explicit connections use Spakky’s `SPAKKY_SQLALCHEMY__CONNECTION_STRING`; Spakky’s default asynchronous support remains enabled. Help opens no database transaction. Bypass attempts lifecycle recording, but failed storage does not prevent bypass. Wiring this command into installed user hooks has not been performed.

The CLI entry point is `neurath.cli:cli`, following the official Typer guide. The module exposes the container-provided Typer object and registers application cleanup at process exit. The async engine is disposed in the command event loop. Transport converts native event strings to `HookEvent`; unsupported events are rejected before database work.

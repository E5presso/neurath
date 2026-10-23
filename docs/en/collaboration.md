# Collaboration and provider execution

This document describes the collaboration library and existing hook integration from #144. Public business CLI options and generated guides belong to #148. Model execution and fulfillment of the user's task are separate outcomes.

## Peers and messages

A peer identifies an observed `HostSession` and optional native child ID. Reconnection reuses that address. Discovery stays within the project; conversations across projects require explicit participants. A session that handed off its work cannot start a new assignment.

Conversation membership and closure are separate from the original message, sender, recipient, reply reference, delivery, full-body reading, and acknowledgment. Closing a conversation preserves its messages and unfinished tasks. Publications select active subscribers from the conversation. Retrying an existing publication does not add new subscribers to its original recipient set. Direct messages and assignments to an explicitly selected inactive peer remain queued for its next connection; the active-subscriber condition does not reject direct recipients.

A connected recipient receives message IDs and titles at its next SessionStart, UserPromptSubmit, or PreToolUse hook. It selects full bodies separately. Returning a summary in a hook response records an attempt, not confirmed reading or task acceptance. Inbox queries neither send messages nor wake peers. Uncertain delivery is inspected using the original message; explicit redrive is allowed only after confirmed non-delivery. Late delivery responses cannot regress reading or acknowledgment.

## Assignments and reports

`PrepareDelegationUseCase` validates and stores the original task definition, source, role, scope, and route. `DelegateTaskUseCase` connects that plan to a peer message or independent provider execution. Peer, native-child, and independent-provider routes are explicit. A worktree or checkout location alone never creates a new session.

A native child must have an observed child address under the actual parent session. Read-only inspection and review reports do not require the parent's workspace writer lease. A provider plan's `parent_session_id` records Neurath assignment responsibility; it does not fabricate native parentage.

Preparation, message assignment, recipient acceptance, progress, and result reports remain distinct. A recipient can execute, test, and report within the existing request without another human message, signature, hash, or approval certificate. Reports retain their executor or reviewer role, original definition, evidence, and remaining work. A report or completed provider process does not mark the original task successful. Task detail includes related assignments.

A committed task correction or cancellation propagates through standard domain events only to that task's assignments. Acceptance, progress, redelegation, and provider start recheck the current request. Late reports stay attached to their original definition and cannot satisfy the corrected request. Unconfirmed external interruption remains `stop_requested` with explicit uncertainty.

## Independent providers

Model discovery uses Codex app-server `model/list` and Claude's initialization control response. Discovery sends no inference prompt. Model selection and execution permission are separate; unsupported policy or implicit inheritance is never silently replaced.

The plan and execution request commit before launching the CLI process. External execution holds no SQLite write transaction. Each assignment has a durable directory containing its original plan, input, output, process identity, and termination observation. Repeated requests and reconnects inspect the same execution without starting another model turn. An uncertain execution directory is neither automatically removed nor replaced.

Codex runs with `--no-daemon`, the explicit sandbox policy, and `approval_policy=never`, separate from shared desktop execution. Claude uses the explicit permission mode and `--permission-prompts none`. Supported modes are checked against installed CLI help.

Cancellation checks the managed PID, start time, and process group before signaling that group alone. Sending a signal is not a confirmed stop. Actual termination evidence is required. Cancellation before launch prevents later launch. Existing user sessions are not concurrently resumed in another process, and the desktop application is not terminated.

## Verification boundary

Regression tests exercise actual SQLite and framework transactions, isolated process execution, retries, late responses, preserved sources and definitions, and cancellation races. Fixture results and observations from installed providers are recorded separately. Verifying this candidate does not imply installation into user projects or activation of an existing desktop connection.

<!-- last_updated: 2026-09-14; synced_from: 243400e58ca74c7fd79bcdd86b488953fa743b97 -->
# Design decisions behind reliable continuation

[한국어](../../ko/contributing/design-principles.md)

A coding agent should keep pursuing the user's requested result while changing ineffective methods. Neurath's design makes that distinction explicit in durable state. For a saved filter that disappears after refresh, the goal is persistence across save and reload; a particular debugging command, implementation plan, or reviewer is a method.

Before reading the rules below, use these terms consistently. A **task** binds a goal to instruction sources and observable **acceptance conditions**. The **root actor** owns that task list within a native **session**. A **worktree claim** records coordinated ownership of the checkout. A **receipt** records one event or report with a specific provenance. A **phase** organizes a skill's procedure, and a **review** assesses a defined scope of work. Their relationships are explained in [architecture](architecture.md).

## Keep the requested outcome stable and methods replaceable

Task definitions retain the goal, source revisions, and acceptance conditions. The owner selects work that still advances an unmet requirement and reuses results that already cover it. When necessary follow-up becomes concrete, it belongs in the task list before the current task is resolved.

A failed persistence approach may justify a new implementation task. It does not justify silently abandoning save/reload behavior, nor does it justify an unrelated framework rewrite. Record the actual outcome of the attempt, retain its history, and define the remaining bounded work from the original requirement. A status question adds conversational context; it does not itself authorize new scope.

The task tools and automatic goal reminder reinforce this judgment. The reminder is reference context, not a classifier that evaluates task necessity or a second completion ledger.

## Use one task list as the task-completion authority

The ledger records `pending`, `in_progress`, `succeeded`, `failed`, and `invalidated`. A native TODO list displays those records in the host's smaller set of visual states. Updating that display cannot create task success. Likewise, a phase label or checkpoint saying “completed” cannot replace task resolution.

This removes duplicate completion accounting while preserving the checks that answer distinct questions: current identity, ownership, exact revisions, delegation results, and the foreground turn. See the [task and TODO contract](task-todo-contract.md) for the distinction between all execution being terminal and all outcomes being successful.

## Let the host establish who is acting

The native host provides session, actor, prompt, and invocation evidence. Named MCP calls use an exact host-issued binding. A tool argument naming a session or project identifies a target; it does not authenticate its caller.

This matters when an implementation agent asks another agent to review the filter API. A same-session subagent and an independent provider session have different native identities and execution arrangements. A recorded assignment or `prepared` result is not proof that either ran. A child cannot inherit root write authority merely because the parent included an identifier in its prompt.

## Keep ownership explicit and local

A worktree claim coordinates which native actor owns work in a checkout. A successful status read neither acquires that claim nor replaces another actor's ownership. Release requires the observed lease epoch and fencing token, so a delayed release cannot retire a newer owner.

Ownership is also separate from host permissions. A valid claim does not widen a sandbox or approve an external effect. Provider plans preserve or explicitly compare execution policy, and the implementation rejects mismatches instead of treating routing success as policy evidence.

## Make state changes conditional and replayable

Mutations use revisions to compare the caller's observed state with the current state. Idempotency keys identify logical operations. Repeating the same operation with the same key and content can return its recorded result; reusing a key for different content is rejected.

The two mechanisms solve different problems. Revision checks prevent an old view from overwriting a new one. Idempotency prevents an uncertain response from duplicating an already accepted operation. Neither permits guessing a new revision or changing a request while keeping its old key.

For example, after an API reviewer reports new evidence, the owner rereads the current task state before resolving the filter task. It does not assume that the list revision captured before review remains current.

## Describe the strength of evidence precisely

Native tool submission, task outcome reporting, review consumption, installation, and app observation establish different facts. A task result artifact identifies the owner, task definition, references, and report. Its `agent-report` assurance does not claim independent semantic verification.

The same discipline applies to provider execution. `accepted` establishes durable admission, a lifecycle event reports progress, and a final authenticated result supplies content to assess. Delivery acknowledgement says the recipient read a message. The owner still decides whether the reported behavior meets the task's acceptance conditions.

## Preserve unfinished work across interruptions

Memory stores context and supports explicit migration. A checkpoint is an agent-authored handoff. A preview is reference data. Adoption is a separate state transition with source-quiescence and revision checks; it does not impersonate the source session. Once migration commits, the source is fenced from further execution writes and retains its historical outcomes.

For the filter example, a useful handoff includes the save/reload reproduction, the changed persistence path, the API review result, the outstanding observation, and the verified project test command. The receiver uses these facts to continue the same goal rather than repeating every earlier command.

## A normal Stop must satisfy the current domain checks

Neurath rejects each current normal Stop until the kernel prerequisites are met. There is no exemption for a status question, elapsed time, repeated rejection, or `stop_hook_active`. The host owns explicit user interruption separately.

The Stop adapter revalidates the current root, turn, transcript, and connection before requesting continuation. A stale or foreign event cannot close newer work or grant another execution turn. A denial means the agent must inspect and address the actual unresolved prerequisite; it is not evidence that a task failed or was cancelled.

## Keep the product independent of its development environment

The package owns its executable assets. Installed projects retain their existing instructions, hooks, permissions, and dependencies. Public documentation describes supported behavior and reproductions without embedding private repository origins, local runtime state, or installation receipts.

When extending Neurath, locate the requirement at its natural boundary: host evidence in the adapter, a domain invariant in the kernel, an operation's input contract in its schema, or a reusable procedure in the source skill. Add validation that observes that boundary. Avoid adding a new ledger, status flag, or gate to restate an existing decision.

Use [runtime lifecycle](runtime-lifecycle.md) for transitions and [task tools](task-tools.md) for exact calls.

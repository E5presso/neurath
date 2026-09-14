<!-- date: 2026-09-14; synced_from: 655c8768709e59b5e5012bab0adc4d888e3e7fa5 + current working-tree source -->

# Reading Neurath's records and tools

[한국어](../ko/terminology.md)

Neurath records what agents requested, what tools executed, and what later checks found. This guide explains the terms used for those records and connects them to exact identifiers you may see in a tool result or the source. A record can describe success, failure, or an outcome that has not been verified.

## Records you may encounter

| Term in the guides | Identifier or source term | What it describes |
| --- | --- | --- |
| Installation record | `install receipt`, `neurath-receipts` | The installed files and the previous bytes, modes, or links needed for restoration. |
| Execution result | `tool receipt`, `ToolReceipt` | A tool invocation's status, output fingerprint, and observed changes. |
| Verification record | `verification receipt` | The checked target, conditions, and observed outcome. |
| Review result | `review receipt` | Findings and the judgment made during a review. |
| Processing record | `source receipt`, `prompt receipt` | An input or event that has been processed. |
| Source information | `provenance` | Where a fact, result, or artifact came from. |
| Host verification | `attestation`, `HOST_ATTESTED` | Evidence from the actual host that establishes the session, actor, or event. |
| Handoff note | `checkpoint` | An agent's account of progress, decisions, evidence, and remaining work. |

The word `receipt` is a technical name for a retained record. In this documentation it does not refer to payment. The interpretation depends on the record's subject: a successful installation record concerns placement, while a live host observation establishes activation. A handoff note tells the next agent what the reporting agent observed; it is not an independent review of that account.

Exact tool arguments remain unchanged even when the guides use a clearer reader-facing term. For example, `--installation-id` identifies an installation record; the legacy `--receipt` alias refers to the same installation operation.

## Work, ownership, and review

| Term | Identifier or source term | Meaning |
| --- | --- | --- |
| Task | Task ledger entry | A measurable piece of requested work with sources, acceptance conditions, dependencies, and an outcome. |
| TODO | Native plan or TODO projection | A display of the task list for the host UI. The ledger retains the authoritative state. |
| Workspace ownership | `worktree claim` | The current session's right to write in a worktree. |
| Ownership key | `fencing token` | A key used with the claim epoch to reject operations from a stale owner. |
| Current turn | `foreground turn` | The host-verified active unit of interaction in a session. |
| Session working state | `enclave` | Bounded, current facts retained for that session's work. |
| Tool call | `invocation` | One call with its exact input and execution context. |
| Reviewer | `evaluator` | The actor that evaluates the assigned candidate and evidence in a review workflow. |
| Decision authority | `oracle_owner`, `OracleOwner` | The user, reviewer, execution result, or official source designated to determine a particular outcome. |

A task outcome is recorded by its authenticated owner. A workflow that explicitly requires independent review has an additional review contract; it does not change every ordinary task into such a workflow. An agent message can provide useful information or request work, but it does not transfer the user's approval, a worktree claim, or reviewer authority.

Project memory stores history that later sessions may retrieve. Session working state keeps the current session's bounded facts. A relationship graph helps explore connections in source and documents. These serve different purposes, so a remembered or graph-derived claim should be checked against the current request and source when it affects a decision.

## Goal reflection and work adoption

Three additional terms describe how work stays connected to its purpose and can move between providers:

| Term | Identifier | Meaning |
| --- | --- | --- |
| Goal reflection | `goal_reminders` | Periodic context that helps the root agent reconsider its method against the original task. It does not score semantic success or change task state. |
| Target-native execution | `target-native` | Explicitly chosen execution using the receiving provider's existing native defaults, hooks, and tool rules. |
| Work adoption | `memory_pull` with `adopt` | Transfer of unfinished tasks and the worktree lease to a verified receiver after the source has settled; ordinary preview and recall do not transfer ownership. |

The [continuity reference](contributing/provider-continuity.md) explains adoption and source resumption fencing; [runtime lifecycle](contributing/runtime-lifecycle.md) explains bounded goal reminders.

## Reading delivery status

Messages pass through several observable stages. The status tells you how far delivery has progressed, not whether the requested work is complete.

| Status | Observed event |
| --- | --- |
| `queued` | The message is durably stored for delivery. |
| `submitted` | The transport accepted the message. |
| `received` | The recipient acknowledged reading the full body. |
| `replied` | The recipient returned a response. |

A response may report completion, a finding, or a request for input. The assigning agent reads it and follows up on the task. See [agent collaboration](usage/agents.md) for everyday use and [the delivery contract](contributing/collaboration-contract.md) for protocol details.

For installation terminology in context, use [installation](usage/installation.md). For exact task fields and transitions, use [the task and TODO contract](contributing/task-todo-contract.md). Installed projects continue to use their own domain glossary; examples such as exporting a work log describe tasks an agent might perform in a target project, not additional Neurath product features.

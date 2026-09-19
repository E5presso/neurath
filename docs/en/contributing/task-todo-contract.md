<!-- last_updated: 2026-09-14; synced_from: 243400e58ca74c7fd79bcdd86b488953fa743b97 -->
# Recording task outcomes and displaying progress

[한국어](../../ko/contributing/task-todo-contract.md)

Neurath's task ledger records the work required by the user. The host's TODO list displays that ledger. This contract lets an agent update visible progress without creating a competing definition of completion.

A **goal** is the required result. A **task** binds a bounded goal to instruction sources and **acceptance conditions**, the observations needed to assess delivery. The native session's **root actor** owns the ledger. A **receipt** records a specific event or report; a task result receipt and a native TODO submission receipt have different meanings. A workflow **phase** organizes a procedure, while a **review** assesses a defined scope. Neither replaces the task's recorded outcome.

## Define behavior before implementation steps

In the running example, a user's web application loses its saved filter after refreshing. A task can require the chosen filter to survive reload, appear correctly in the UI, and still apply to the displayed results, with existing default behavior covered. Reproducing save/reload, changing persistence code, and reviewing the API contract support those observations.

A task definition contains:

| Field | Meaning |
| --- | --- |
| `key` | Stable identity for this definition within the session |
| `title` | Short, readable label used in progress display |
| `goal` | Bounded result that advances the user's requirement |
| `sources` | Instruction provenance: `prompt`, `ticket`, or `spec`, each with a reference and revision |
| `acceptance` | One to 32 observable conditions |
| `dependencies` | Existing task identifiers that must settle before this work starts |

The runtime adds the canonical producer and result-evidence contract. Definition identity includes its source revisions and acceptance conditions. Reusing a definition key with different content is rejected. New necessary work is appended as a new definition; terminal history is immutable.

## Admit tasks from real instructions

Task mutations require the verified native root, an active foreground turn, and current native admission. Initial intake needs the current native user instruction receipt or an explicit retained prompt source from the same session. Ticket and specification references can supplement the native instruction source.

When a new prompt arrives after tasks already exist, appending work must explicitly select the original requirement or an explicit new request. The service rejects implicitly treating a status question as fresh scope. A peer-resumed turn can use retained, validated same-session prompt sources without fabricating a new user receipt.

`task_list` returns `current_prompt_source` and each task's stored sources. Copy observed source references and revisions when a call requires explicit provenance. Do not invent prompt identifiers.

## State transitions and revisions

| State | Meaning | Terminal? |
| --- | --- | --- |
| `pending` | Defined but not started | No |
| `in_progress` | Selected for execution | No |
| `succeeded` | Owner reports acceptance met | Yes |
| `failed` | Owner reports an actual unsuccessful outcome | Yes |
| `invalidated` | Owner reports why the task no longer applies | Yes |

`task_start` starts only a pending task. It requires all dependencies to be terminal. A successful resolution also requires terminal dependencies; a failure or invalidation can be recorded before they settle. Settlement is the runtime check, so an agent must assess the meaning of failed dependencies rather than assume that every terminal dependency succeeded.

Resolution can record an outcome for a nonterminal task; the model is not limited to a strict pending → running → success chain. Each mutation compares the exact list revision, and start/resolve also compare the exact task revision. A stale comparison produces a conflict rather than silently changing the newest state.

Use the returned revision from a successful mutation or a fresh `task_list`. Stable operation keys support identical retries. A key reused with changed content is a contract error.

## Result reports and the limits of assurance

`task_resolve` requires `status`, `references`, and `summary` alongside identity and revision fields. The service creates a content-addressed `neurath.task-result.v1` report containing the task definition digest, owner, outcome, summary, and references. The ledger read checks that the artifact is present, intact, and identifies the same task.

The report's assurance is `agent-report`. The runtime preserves the report's origin and integrity; it does not independently prove that the application now retains its filter. The owner must connect observations to acceptance and describe any limits in the evidence.

Before resolution, register any discovered necessary follow-up not already covered. A failed task should state the unmet condition, actual blocker, and next action. Elapsed time, a side question, or a rejected Stop does not establish failure or cancellation. Required work can continue through a new task while retaining the failed attempt's history.

The list exposes three useful summaries:

| Field | Interpretation |
| --- | --- |
| `all_terminal` | Every recorded task has a terminal outcome, and the list is nonempty |
| `all_succeeded` | Every recorded task reports success, and the list is nonempty |
| `unsuccessful_task_ids` | Tasks whose outcomes are `failed` or `invalidated` |

A later successful follow-up does not erase an earlier failure. Explain how later evidence covers remaining requirements when reporting overall delivery.

## Project the full list to the native host

`task_list` and task mutations return `todo_projection` and `native_todo`. The latter supplies the host tool and exact arguments: `update_plan` for Codex, `TodoWrite` for Claude Code. Use that returned projection, including all current rows.

`native_todo.display_status` is `pending`, `current`, or `empty`, based on actual host submission receipts. If a changed ledger has not been displayed, the next ordinary native tool call receives a reminder with the exact projection once for that revision. This is a display reminder, not another completion gate. Record independently verifiable work as it happens and update the native list before reporting a percentage. During recovery bypass, keep the host TODO current and reconcile the ledger after recovery.

Codex 0.152.0 made `update_plan` opt-in. Installation adds `tools.update_plan.enabled = true` when neither the project nor the user's configuration already selects a value. Claude Code's current default is the Task tool family, and some versions also require explicit opt-in for task tools on newer models. Neurath uses the officially supported whole-list `TodoWrite` display for its existing task ledger: when unset, installation supplies `CLAUDE_CODE_ENABLE_TODO_TOOLS=1` and `CLAUDE_CODE_ENABLE_TASKS=0` in project settings. Explicit project, user and environment choices are preserved. If they select another task interface or disable the tools, do not claim that `TodoWrite` is available. Reload the host after changing tool exposure and verify a real native invocation.

Both hosts have fewer visual states than the ledger. The projection maps every terminal task to native `completed`, and includes the real outcome in text. Only the first running task uses the native `in_progress` state; other running tasks remain identifiable through their text. Every row includes the task identifier and list revision.

Consequently, a native completed checkbox may represent `Failed` or `Invalidated`. Read the label or ledger outcome before describing success.

Returning the projection does not display it by itself. The MCP text response and `native_todo.display_instruction` ask the agent to publish a changed projection immediately through the named native tool with its exact arguments. If that tool is absent from the current tool catalog, report the missing native capability and retain the display requirement. An inline checklist, file panel, or synthetic event is not the native TODO display and must not be substituted or recorded as a successful submission. Do not repeat an unchanged display or create a second task ledger.

## Observe submission without treating it as completion authority

Native `PreToolUse` records the prepared invocation after comparing its complete rows with the current ledger projection. The paired result must match that request. Codex may include a textual `explanation` in addition to the exact canonical rows.

A submission receipt can be `submitted`, `current`, `stale`, or `failed`. `current` requires a successful native result and an unchanged projection digest. A successful submission becomes stale if the task list changed before its result was recorded. Capability observation is `unobserved`, `observed-supported`, or `unsupported-runtime`.

These receipts have scope `native-tool-submission`. They do not establish task success or app rendering. A stale display or display failure cannot rewrite the ledger or become a duplicate ordinary task-completion gate. Refresh the display from current task state when the native capability is available.

## Close and migrate without losing work

The current ledger check shares the transaction that closes the root turn, so a newly appended task cannot be missed between an earlier read and closure. Unsettled tasks reject normal Stop. An already registered ledger is the task-completion authority; checkpoints, learning, TODO state, and independent review are not additional ordinary task-completion votes. Explicitly selected phase or review contracts retain their own requirements.

A committed memory adoption preserves source outcomes and records `superseded_by`. The migrated source is barred from further task mutations, while the receiver continues imported unfinished work under its own native identity. Migration does not rewrite unfinished source history as success.

Use [task tools](task-tools.md) for concrete argument examples and [runtime lifecycle](runtime-lifecycle.md) for goal reminders and normal Stop behavior. Source definitions are in `task_ledger.py`, `task_service.py`, and `task_todo.py` under `src/neurath/_assets/scripts/agent_harness/`, with native adapters under `src/neurath/runtime/`.

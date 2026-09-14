<!-- date: 2026-09-14; synced_from: 655c8768709e59b5e5012bab0adc4d888e3e7fa5 + current working-tree facts -->

[한국어](../../ko/contributing/task-todo-contract.md)

# Requested work and the native TODO display

The task ledger preserves what the user asked to accomplish. The host's plan or TODO list makes that work visible during execution. The ledger owns task state; the display is a projection that can lag or fail without changing the recorded outcome.

## Define measurable work

Each task has a stable ID, a revision and a definition containing `key`, `title`, `goal`, `sources`, `acceptance` and `dependencies`. A source records `kind` (`prompt`, `ticket` or `spec`), `reference` and `revision`. Source revisions and acceptance conditions are part of the definition digest, so an outcome cannot silently migrate to a different goal.

Only the authenticated native root owner in an active foreground turn can mutate tasks. Intake requires a native user-instruction receipt. When `sources` contains no prompt source, the service retains the current native prompt automatically. A supplied prompt source must match an existing receipt belonging to that owner; a fabricated prompt reference is rejected.

`task_define` appends definitions and preserves earlier task history and dependencies. The task key gives a definition stable identity within its session. Use returned IDs for dependencies, not titles or invented IDs. To represent a superseding request, retain the old terminal history and append the new measurable work.

## Define follow-up as work becomes clear

Task planning is incremental. Begin with the requested outcome and the work already understood. When investigation, implementation or validation reveals a necessary next step, register it with `task_define` while the context is available, rather than leaving it only in a report. Before adding or selecting a task, judge which unmet user requirement it advances, whether existing results already cover it, and whether its scope merely perfects a chosen method. Record the bounded outcome in the existing `goal` and `acceptance`, using the original instruction `sources`; no additional judgment schema or approval step is required.

Before `task_resolve`, ensure discovered necessary follow-up is tracked. Preserve old terminal history and reconcile it with later results; continue only the still-required work through `task_define` and `task_start`. Do not duplicate completed work, reopen cancelled requirements, or turn an answer-only request into execution. Task count is not a reason to omit necessary work or invent more work.

In addition to periodic reminders, authenticated root `PreToolUse` hooks for the three named task mutation tools deliver a bounded goal reflection at each distinct invocation. This also covers the first definition when the ledger is empty and prioritizes the selected task when available. Tool descriptions provide the same guidance before choosing the call. Delivery preserves the ledger, native permissions and existing hook decisions; the agent judges relevance and scope. Tests can verify delivery and state preservation, but cannot prove every semantic judgment will be correct.

## State and dependency rules

| State | Meaning | Native display status |
| --- | --- | --- |
| `pending` | Defined work not started | `pending` |
| `in_progress` | Work started | First active row: `in_progress`; further active rows: `pending` |
| `succeeded` | Owner reports the acceptance outcome was achieved | `completed`, with `Succeeded` in the row text |
| `failed` | Owner records an actual terminal failure | `completed`, with `Failed` in the row text |
| `invalidated` | Owner records a real cancellation or superseding decision | `completed`, with `Invalidated` in the row text |

Both hosts have three visual states. The readable row therefore preserves the five-state task result and all parallel work. Showing only one active visual row does not mean only one task can be running.

`task_start` accepts only a pending task whose dependencies are terminal. Resolving as `succeeded` also requires terminal dependencies, even when no separate start was recorded. `failed` and `invalidated` can be recorded before dependencies settle. A terminal dependency can itself have failed or been invalidated; that condition establishes ordering, while the dependent task's acceptance criteria still control its claimed result.

A terminal task has immutable evidence and cannot be reopened by editing its display. Failure and invalidation must describe the real outcome; they are not shortcuts for hiding unfinished requested work.

## Record the result once

`task_resolve` takes the exact task and list revisions, a terminal status, a concise summary and 1–32 distinct references. References can point to the actual source, check, pull request or cancellation decision relevant to that result. The service stores a content-addressed result report that binds the task ID, definition digest, owner, status, references and summary.

The report uses `schema=neurath.task-result.v1` and `assurance=agent-report`. This authenticates who reported what. It does not independently certify every acceptance condition. Ordinary completion does not require a separate material batch, workflow, per-criterion report or independent task reviewer. An explicitly requested review workflow keeps its own evaluation contract.

Use the mutation response's returned revisions for the next operation. A stale revision produces `revision-conflict`. Re-read after a real conflict or interruption, and preserve the same key only for an identical uncertain request. A changed request needs a new key. Reusing a key with different input is rejected.

### Read terminal outcomes without losing the goal

`all_terminal` reports that all execution records have ended. `all_succeeded` is true only for a nonempty list whose tasks all succeeded; `unsuccessful_task_ids` identifies failed or invalidated tasks. These are views of the same owner-reported ledger, not independent certification. A failed attempt, Stop rejection, elapsed time, or a status question is not evidence that the user cancelled the original goal. Failure reports retain the unmet condition, actual blocker, and next action.

Task intake requires a verified native user instruction source. A peer-resumed turn can explicitly reuse a retained prompt source from the same session even when `current_prompt_source` is null; each item in the request must supply that source. The service checks its owner, reference and digest without creating a new user receipt. After a prompt not yet referenced by the ledger, explicitly select the relevant source when defining work. Preserving provenance does not establish semantic approval for expanded scope. Periodic [goal reminders](runtime-lifecycle.md) help the agent retain this distinction without changing the ledger.

To prepare a native child on such a peer turn, supply the in-progress task's `task_id` and `expected_task_revision` together to `delegation_prepare`. The intent binds the task definition to the current native generation and turn. Spawn and attachment revalidate it, including at transaction commit; completed tasks and stale turns cannot authorize new child work. Native parent/child attestation and current execution permissions remain required. An accepted peer message alone does not provide this authority.

An already-issued child can still store and return its result through the named `artifact_put` and `evaluation_report` tools after the parent task ends. This exception remains bound to the existing delegation and retained instruction source; it does not authorize further execution or let the child consume its own report.

## Submit the exact projection

Task results provide `native_todo` with `tool`, `arguments`, `list_revision`, `projection_digest`, `task_ids` and a capability observation. The host adapter uses the specified native tool. For Codex it is `update_plan`; for Claude Code it is `TodoWrite`. The receipt's scope is `native-tool-submission`.

A row has this exact form:

```text
[Neurath] TITLE (DISPLAY_STATUS; TASK_ID; list LIST_REVISION)
```

The following are structural examples. In a live call, copy all rows and values from the current `native_todo.arguments` rather than constructing the identifiers shown here.

```json
{
  "plan": [
    {"step": "[Neurath] Verify parser behavior (In progress; TASK_ID; list 2)", "status": "in_progress"}
  ],
  "explanation": "The task has started; acceptance checks are in progress."
}
```

```json
{
  "todos": [
    {
      "content": "[Neurath] Verify parser behavior (In progress; TASK_ID; list 2)",
      "activeForm": "[Neurath] Verify parser behavior (In progress; TASK_ID; list 2)",
      "status": "in_progress"
    }
  ]
}
```

Codex may include a string-valued `explanation` beside the exact canonical `plan` rows. This field is excluded only when comparing the projection shape. The complete original input, including that explanation, remains in the request digest paired with the host result. Nontext explanations, omitted tasks, reordered or edited rows, extra projection fields, and substituted result input are rejected. Claude's `content` and `activeForm` are the same returned row text.

## What the submission receipt proves

| Receipt state | Observation | Recovery |
| --- | --- | --- |
| `submitted` | A verified root submitted the exact current projection under a native invocation ID. | Wait for that invocation's real result. |
| `current` | The paired native result succeeded and the projection still matches the ledger. | Continue from ledger state. |
| `stale` | The result succeeded after the task projection changed. | Submit the newly returned complete projection. |
| `failed` | The native tool reported failure. | Retain task truth and diagnose the display failure. |

A result needs its prepared native request. Host, tool and complete input digest must match. Duplicate consistent events are idempotent; contradictory outcomes or changed invocation identity are rejected. Only a successful current projection becomes the latest published projection record.

Capability observation is `unobserved`, `observed-supported` or `unsupported-runtime`. A missing or failing native display must not be reported as a successful UI update. These submission records establish the native tool interaction; they are not independent inspection of rendered pixels.

## Stop uses the latest task state

When a canonical task list exists, the Stop transaction checks that its nonempty task set is entirely terminal before closing the root turn. The check and closure are atomic, so another accepted task cannot disappear between them. `task_list` returns `all_terminal=false` for an empty list; absence or emptiness does not establish completion.

TODO display failure, stale display, unavailable display, checkpoint state and learned guidance do not add completion votes. Sessions without a task list retain their existing legacy Stop rules. The user-facing result should distinguish achieved work, real failure and cancelled scope rather than treating every visual `completed` row as success.

Implementation: [task ledger](../../../src/neurath/_assets/scripts/agent_harness/task_ledger.py), [task service](../../../src/neurath/_assets/scripts/agent_harness/task_service.py), [TODO adapter](../../../src/neurath/_assets/scripts/agent_harness/task_todo.py). Regression contracts: [task tools](../../../tests/test_task_tools.py), [TODO receipts](../../../tests/test_task_todo.py), [result acceptance](../../../tests/test_task_acceptance_review.py). See [task tool reference](task-tools.md) for exact input limits and response shapes.

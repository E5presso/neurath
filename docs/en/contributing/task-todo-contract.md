# Tasks and session completion

**English** · [한국어](../../ko/contributing/task-todo-contract.md)

**Keep working while a registered task is unfinished; record each result once.**

## Task list

The agent decomposes user prompts, tickets and specifications into measurable tasks.
Each task has a stable ID, a goal, acceptance conditions, source references and a status.
The list lives in the project SQLite database. Tasks can be appended while work is running;
existing identities, results and dependencies remain intact.

The four task tools are:

| Tool | Purpose |
| --- | --- |
| `task_define` | Append tasks with their goal, sources and acceptance conditions. |
| `task_list` | Read the current list, revision and TODO projection. |
| `task_start` | Mark a task in progress. |
| `task_resolve` | Record success, failure or invalidation with a summary and evidence references. |

Resolution is the authenticated task owner's report. It requires no separate workflow,
per-condition acceptance report or independent task reviewer. A test result, source location,
pull request or user cancellation can be referenced directly. The agent must explain what
actually happened; the harness records that report without claiming independent certification.

Statuses are `pending`, `in_progress`, `succeeded`, `failed` and `invalidated`.
The last three are terminal. Failure and invalidation describe real outcomes, not shortcuts
for hiding unfinished work. Old result records retain their original assurance labels.

## Stop and visibility

When a task list exists, it is the completion authority. Stop reads the latest list in the
same SQLite transaction that closes the turn and rejects unfinished tasks. A concurrent
addition therefore cannot be lost between checking the list and closing the turn.

Workflow, review, checkpoint, learning and TODO display records are not additional completion
votes. Existing sessions without a task list keep their legacy workflow rules; no successful
task list is fabricated from old workflow history.

Native TODO tools display the list. A failed or stale display update does not change task
truth and does not veto completion. Available displays should still be kept current.
Display receipts describe actual submissions; an unavailable UI is never reported as updated.

## Tests and editing

Use the host's ordinary editing and command tools. File ownership and native permissions
still apply. Preparing and resolving a material batch is no longer required for ordinary edits.
Material and verification bookkeeping tools are omitted from the public MCP catalog;
legacy calls remain readable/executable for recorded integrations.

A registered test executes under the admitted policy and returns its actual result, including
source fingerprints. A later question cannot turn a completed test into an authorization
failure. Tests do not automatically create a second completion ledger or a Stop retry loop.
Run the repository's required checks on changed source and describe failures honestly.

## Bypass switch

Use `harness_bypass(enabled=true)` to suspend all Neurath hook constraints for the
current worktree, `enabled=false` to restore them, or omit the value to read the mode.
The switch works without a normal hook binding, so bypass cannot lock out its own disable
operation. It does not alter native host permissions or delete task history. Ordinary Neurath
MCP operations still require native bindings and are unavailable while hooks are bypassed.

Tool results carry structured data once, with a short text status. Task mutations return
IDs, statuses and TODO display data; full definitions remain available through `task_list`.
Automatic memory context is limited to 3 KB at session start; later questions do not replay it.

## Storage and installation

Mutable task and runtime state uses SQLite. JSON remains a serialization format and a format
for versioned project configuration, manifests and external outputs.

Legacy migration preserves task identities, revisions and references transactionally.
Stop old writers before switching the live installation to SQLite. Detecting a changed legacy
file is not a substitute for stopping that writer. Preserve recovery data until cutover is verified.

Model catalogs are reused within a native issuer/provider session. Refresh only when requested
or when there is concrete stale-catalog evidence. Bulk messaging commits messages atomically
and delivers them to the specified recipients; delivery is separate from task completion.

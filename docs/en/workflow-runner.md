# Workflow runner

[한국어](../ko/workflow-runner.md)

The new core workflow runner implements #141 on top of the task ledger. It is an internal Python use-case API; the CLI, runtime hooks, provider adapters and independent evaluation policy are separate tickets. It does not activate the installed 0.3.1 runtime.

`transport.core_requests.build_workflow_runner(path)` constructs a stateless `WorkflowRunner`. Explicit `CoreDatabase.initialize()` upgrades the new core schema from `core_0002` to `core_0003`; ordinary requests do not migrate. The migration preserves existing identities, sources and unfinished tasks. Original legacy databases are not opened.

## Definitions and execution

`Definition` fixes a name, version, original purpose, required inputs and ordered `Phase` values. Each phase binds its action to a target and target revision, result conditions, optional named reviewer, dependencies, conditional input and execution/retry limits. Target revisions are observations supplied by the host, such as an actual artifact digest or Git revision; callers must refresh them when the relevant target changes.

`start(project_id, task_id, definition=..., inputs=..., expected_task_revision=...)` fixes a definition and returns a run. `current` and `history` only read. The run exposes its current phase, inputs, conditions, status, reasons and attempt counts. Selected unfinished procedures prevent the existing task result path from declaring success.

`dispatch(..., phase_id=..., expected_revision=..., host=...)` persists an execution attempt, commits the transaction, then calls `ExecutionHost.execute`. `report_result(..., attempt_id=..., observation=...)` deduplicates the observation and advances only the matching current attempt, generation and target revision. Successful results must satisfy all phase conditions and the named reviewer, when configured. Failed reviews retain defects and attempted changes. Retry and repeated-no-progress bounds keep the loop finite. Procedure completion is automatic and idempotent; it leaves user-goal success to the task result use case.

The host protocol has `execute`, `lookup`, `notify` and an explicit `deduplicates` capability. Native permissions remain the host's responsibility. A provider or native tool adapter can execute the action or delegate it to a reviewer and return its observed evidence. A reviewer name is ordinary attribution, not an authentication or approval system.

`CommandHost(directory)` executes argv directly without shell interpolation. It drains output while retaining only the configured prefix, enforces a real timeout, supports cancellation through a `threading.Event`, kills the process group on interruption and reports actual exit observations. It only supplies the mechanical `execution` condition; it cannot produce a semantic review. Its notification path writes to stderr by default, or uses an injected real delivery function. A failed notification raises after the waiting result is persisted.

## Recovery and corrections

When dispatch loses its response, the attempt remains waiting. `reconcile(..., attempt_id=..., host=...)` first asks the host for the same result. It reuses the same external idempotency key only when the adapter explicitly guarantees deduplication. Without lookup or guaranteed deduplication it persists an unknown result and delivers a notice; it never blindly repeats the mutation. The local command adapter has no durable external receipt or deduplication, so a process lost across restart requires an external observation through `report_result`.

A delayed result from a failed or superseded attempt remains history and cannot complete the newer attempt. An observation received while the task correction is unreconciled remains unapplied. Once an unrelated correction is reconciled, the identical observation can apply to the still-current attempt without executing again.

`revise(..., definition=..., inputs=..., reason=..., correction_source_id=None, invalidate=())` preserves old definitions and results. Method edits retain the original goal and required conditions; scope changes refer to the current correction already applied to the task. Changed phase contracts and declared dependents are invalidated; unchanged phases keep their valid evidence. Input changes conservatively invalidate all phases. `invalidate` explicitly marks related evidence stale after a new relevant failure, even if the target identifier did not change. Outstanding affected external mutations must be reconciled before revising them. Method edits cannot replenish exhausted retry budgets.

`skip` records the reason for a current optional phase or a false branch explicitly defined by its input condition. Removing required scope requires a real correction. `yield_run` stores the actual pause reason and `resume` preserves the same run and outstanding attempts. These APIs record lifecycle state; runtime ticket #142 must connect native control return and ownership checks.

## Verification boundary

Tests use temporary SQLite databases and real local subprocesses. They cover required phase integrity, failure/retry, branch skipping, lost response lookup and notifications, bounded execution, targeted evidence invalidation, delayed results, finite review rounds and schema upgrades. They do not prove installed-host activation, real provider delivery, independent evaluator quality or release readiness.

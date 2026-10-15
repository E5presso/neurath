# Task requirements, attempts and TODO

Issue #140 extends the project/session foundation with attributed sources, current
requirements, attempt outcomes and append-only requirement history. Each operation
has an immutable command or query in `application/ports/usecases`, an ABC
`I…UseCase`, a nominal `…UseCase.execute` implementation, and an individual
`transport/<operation>.py` request function. There is no ledger façade, custom unit
of work or compatibility alias for the rejected APIs.

Each transport function accepts its command/query and optional `database_path`.
It opens a fresh SQLAlchemy `Session`, directly enters `session.begin()`, checks
the schema and project/session, and supplies explicit repositories to that use
case. Repositories flush changes; the request owns commit, rollback and disposal.
Reads use SQLite read-only connections. A write reservation protects the complete
read-modify-write operation, with expected task revisions rejecting stale callers.

| Operation / request type | Observable behavior |
| --- | --- |
| `record_source(RecordSourceCommand)` | Preserve exact text, author, reference and origin session. `SourceKind` distinguishes instruction, correction, status question and summary. A correction identifies an existing actionable source in the same project. |
| `create_task(CreateTaskCommand)` | Create a pending requirement linked to an instruction. Existing project sources can be reused by explicit ID in another session; attribution is preserved and is not a human reapproval gate. Optional dependencies and `follows_task_id` retain related work. |
| `correct_task(CorrectTaskCommand)` | Require the current source lineage and expected task revision. Change only supplied title, expected outcome or dependencies; omitted fields and other tasks remain unchanged. Increment definition revision, retain the original source and history, and make the corrected task pending. |
| `invalidate_task(InvalidateTaskCommand)` | Apply an attributed cancellation with a reason. Preserve outstanding attempts; this does not claim physical execution stopped. |
| `start_task(StartTaskCommand)` | Require pending/failed work and succeeded dependencies; return a fresh `TaskAttempt`. Starting records bookkeeping, not actual execution success. Failed attempts remain when work is retried. |
| `report_task_result(ReportTaskResultCommand)` | Require the attempt's executor, summary and evidence. `SUBMITTED` preserves submission evidence without completing the attempt or task. `SUCCEEDED` requires no remaining work. `FAILED` and `PARTIAL` require remaining work or a concrete blocker and leave the task failed/retryable. Terminal reports are immutable. |
| `wait_task(WaitTaskCommand)` | Record an `ExternalWait(target, condition, continuation, evidence)` for unfinished work. All fields are required; a generic reason alone is insufficient. Independent work remains ready. |
| `resume_task(ResumeTaskCommand)` | Require release evidence and the current revision. Preserve an outstanding attempt instead of automatically submitting another execution. |
| `get_tasks(GetTasksQuery)` | Return every current task in the requested session as a `TaskProjection`; `ready` derives runnable work from the same collection. |
| `get_task_history(GetTaskHistoryQuery)` | Return complete requirement snapshots and operation reasons in task revision order. |
| `get_task_attempts(GetTaskAttemptsQuery)` | Return all attempts, including failures, partial outputs, submissions, outstanding attempts and results superseded by corrections. |
| `get_sources(GetSourcesQuery)` | Return exact source records originating in the requested session. Reusing a source does not duplicate or rewrite its origin. |

Task states are `pending`, `active`, `waiting`, `succeeded`, `failed` and
`invalidated`. `TaskProjection.all_terminal` includes failure and invalidation;
`all_succeeded` requires actual success on every current task. Both are false for
an empty collection: absence of tasks does not establish completed requirements.
The TODO is this projection, not a second writable status store. Display failure
or host status abbreviation cannot alter persisted outcomes.

Task `revision` fences every state change. `definition_revision` changes only
when the requirement is corrected or invalidated. An attempt retains its original
definition revision and executor. A late report is saved on that attempt but
cannot finish a newer definition or a cancelled task. A failed task may be retried
or have a same-source follow-up task; its original failure remains visible.
Dependencies are session scoped, reject cycles and require actual success.

## Storage and migration

`RequestSource`, `Task`, `TaskAttempt` and `TaskChange` have separate ABC repository
ports and nominal SQLAlchemy adapters. Typed declarative models use
`Mapped`/`mapped_column` with explicit `from_domain` and `to_domain` conversions.
Model discovery registers the full metadata from any request import.

Explicit `SqliteDatabase.initialize()` applies `core_0002` after the unchanged
`core_0001`. The migration adds `task_sources`, `tasks`, `task_attempts` and
`task_changes`, preserving existing identity rows and foreign keys. New
initialization and an upgraded 0001 database produce equivalent schemas. Requests
never migrate implicitly. Destructive downgrade is rejected to preserve source
and task history. This replaces the uninstalled draft schema from the rejected
PR implementation; converting original 0.3.1 user databases remains separate work.

## Validation and boundaries

Tests cover A01, A04, A05, A06, A44 and B04: provenance reuse, narrow corrections,
full TODO states, failed/partial/submitted attempts, stale outcomes, external waits,
independent readiness, dependency cycles, cross-scope rejection, concurrent starts,
transaction rollback, fresh-process reads, and 0001 preservation/schema equivalence.
The entire source tree passes the base quality hook's strict typing, formatting,
docstring and architecture checks; there is no task-specific exclusion.

Evidence strings record caller observations; they do not prove remote execution,
authenticate a human, or evaluate artifact semantics. Host adapters must supply real
observations and the future phase runner must enforce required evaluation before
reporting completion. Public CLI wiring, monitoring, Stop hooks, evaluation,
installation and live activation remain outside this change. No current user DB
or installed distribution is modified by these temporary-database tests.

# Sources, tasks and TODO ledger

[Documentation](index.md) · [Core foundation](core-foundation.md) · [한국어](../ko/task-ledger.md)

#140 connects original requirements, corrections, current work and attempt submissions/results
in one SQLite ledger. These are internal Python request APIs. Public CLI, host hooks and the
phase runner remain subsequent work.

## Domain and persistence

`RequestSource` retains original text, author context, references, first session and correction
parent. Another session in the same project can reuse the source ID without another human
prompt or an author authentication gate. Status questions and historical summaries are retained
as context but cannot define requirements or impersonate corrections.

`Task` owns its definition history, all attempts and external wait/resolution history. These
children have no independent repositories. Both aggregates use Spakky `AbstractAggregateRoot`;
owned records are immutable values. Ports and adapters inherit `IGenericRepository` and
`AbstractGenericRepository` constructors, CRUD and batch operations. The only added SQL is
project-scoped full-list lookup.

`@Table`, `AbstractMappableTable`, owned relationships and `SchemaRegistry` map complete
aggregates. Each request uses the actual `ConnectionManager`, `SessionManager` and `Transaction`.
Successful requests commit once; failures roll back all parent/child changes. Integer revisions
and the inherited repository's optimistic checks reject stale mutations.

Dependency scope, duplicates and cycles are checked by `Task.validate_dependencies()` against its own identity and current or proposed dependencies. Original-text, definition, observation and wait validation also belongs to each aggregate/value object.

## States and observations

| State | Meaning |
| --- | --- |
| pending | A required result remains and a new attempt can start |
| active | Work is underway against the current requirement revision |
| waiting | The current attempt depends on an actual external event |
| succeeded | The current revision has a successful observed result |
| failed | A failed attempt and remaining requirement are retained for retry |
| invalidated | An actual correction invalidated the requirement; this is not success |

Starting binds the revision and session to an attempt without executing or resubmitting an
external command. Submission records candidate material without setting success. Results need
observation references; success cannot contradict a failed exit code or remaining work. Failed
and partial results must state remaining work. Partial work becomes pending. Retrying allocates
a new attempt while retaining previous results. Identical confirmed reports are idempotent;
contradictory reports cannot overwrite them.

Corrections connect an actual correction source to the current requirement and modify only
specified fields. Unchanged values do not reopen completed work. Changed values append a
revision, retain previous definitions/attempts and return the requirement to pending. Late
results remain in history without completing a corrected requirement or reviving invalidated
work. Sibling tasks and original source text are preserved.

External waits record a target, resolution condition, authorized continuation scope and observed
state. Resume records the observed resolution and continues the same attempt without automatic
external resubmission. Independent work remains ready. Dependencies must reference actual tasks
in the same project; duplicates, self-dependencies and cycles are rejected. Only successful
prerequisites satisfy the start condition.

## Internal request API

Operations are individual use cases in `application/usecases`, invoked through `run(command/query)`.
They implement Spakky `ICommandUseCase`/`IQueryUseCase` with `AbstractCommand`/`AbstractQuery` inputs.
Each use-case module defines its input and Result DTO together. Results carry domain data and query output. Callers use the request container and standard
Transaction shown in the core example. Mutations identify project, owner session,
target and observed revision. Source creation returns a `RequestSource` through
`RecordSourceResult.source`; task creation returns a `Task` through `CreateTaskResult.task`.
Read the identifier from the returned object's `uid`.

| Request | Behavior |
| --- | --- |
| record_source | Preserve original text, references, author context and correction relationships |
| create_task | Bind required work, result, dependencies and follow-up to an existing source |
| start_task | Begin an attempt against the current definition |
| submit_result | Preserve candidate material separately from success |
| report_result | Retain observations, failure, partial work and remaining requirements |
| correct_task | Modify only selected fields using an actual correction |
| wait_task | Record the active attempt's external dependency |
| resume_task | Record resolution and continue the same attempt |
| invalidate_task | Invalidate through correction while retaining history |
| get_sources | Read originals and correction lineage |
| get_tasks | Read the full current list and its TODO projection |
| get_task | Read current state and complete definition/attempt/wait history |

TODO is not another ledger. `get_tasks` returns all current tasks owned by the requested session;
readiness uses prerequisite states across the same project. All-terminal differs from
all-successful, and an empty list is not completion evidence. Client display copies, status
simplification or rendering failure cannot mutate the ledger.

Homogeneous collection contracts use `Sequence[T]` across repositories, domain inputs and responses.
Sequence is a read interface, not a runtime immutability guarantee. Owned histories and response lists
use concrete tuple snapshots; dependency inputs are copied so mutating a caller list cannot alter requirements.

## Schema, verification and boundaries

Explicit initialization adds `core_0003` without modifying `core_0001` or `core_0002`. Existing
projects, sessions, integer revisions, unrelated original tables and unfinished records remain.
Failures roll back new tables and revision together. Downgrade is rejected when sources or tasks
exist; only an empty ledger can be removed. Ordinary requests do not migrate implicitly.

A01/A04/A05/A06/A44/B04 are covered by domain tests, actual SQLite/Spakky requests, independent
process reads, concurrent starts, a real exit-7 failure and generated artifact, late reports,
source reuse, scope/cycle rejection, transactional rollback and old-store migration. Existing
whole-product 100% statement/branch and zero-exclusion checks remain enforced by the required
runner and CI.

References record caller observations; a string is not independent proof of remote execution
or human authentication. Host observation integration, runner, completion/third-party evaluation
and actual installation/cutover remain subsequent tickets. Tests use temporary stores and do
not modify user databases or installed distributions.

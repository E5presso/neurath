# Project and session foundation

[Architecture](architecture.md) · [Implementation plan](implementation-plan.md) · [한국어](../ko/core-foundation.md)

#137 manages projects and sessions per request in a user-wide SQLite database.
Dependencies use the official Spakky 8.2.0 release, including post-commit event publishing, in-process setup and request isolation fixes. All direct Spakky dependencies use this version, with published packages locked by `uv.lock`. No temporary Git pins or local path dependencies are required.
The candidate provides hook, memory and handoff CLI commands; remaining commands and installation remain subsequent work.

## Framework components and responsibilities

- `Project` and `HostSession` use `@mutable` and `AbstractAggregateRoot[UUID]` for identity, equality and change tracking. Project owns `ProjectLocation` as an `AbstractValueObject`.
- The existing `id` reference remains a read-only compatibility property over `uid`. Identity selection, folder promotion, ownership conflicts, session scope and movement remain domain rules.
- Repository ports reuse standard `IAsyncGenericRepository` aggregate CRUD. Aggregate lookups by location or native identity are repository contracts for commands. CommandUseCases do not depend directly on SQLAlchemy sessions, queries or ORM models.
- `SQLAlchemyProjectRepository` and `SQLAlchemySessionRepository` inherit `AbstractAsyncGenericRepository`. They do not redefine constructors, `get`, `get_or_none`, `contains`, `range`, `save`, `save_all`, `delete`, or `delete_all`.
- Domain tables use `@Table(Domain)` and `AbstractMappableTable[Domain]` with explicit conversion. Owned location records use `AbstractTable` without a separate domain repository.
- `SchemaRegistry` resolves domain/table mappings from Table tags. Repositories do not maintain another mapping registry.
- `ApplicationContext` composes `@UseCase`, `@Repository`, observation Pods and the framework's `AsyncConnectionManager`, `AsyncSessionManager`, `AsyncTransaction`, and `AggregateCollector`.
- Callers directly await `run(command/query)` on container-resolved use cases. The official `@transactional` advice owns commit, rollback and session closure.
- Every use case implements Spakky `IAsyncCommandUseCase` or `IAsyncQueryUseCase`; inputs inherit `AbstractCommand` or `AbstractQuery`. Dedicated Command/Query and Result DTOs live with their owning UseCase. Returning an existing domain type does not require an extra DTO.
- Framework missing-entity and storage version-conflict errors propagate through their original contracts. Use cases ask the domain to validate session/project scope.

SQL for basic CRUD, merge, flush and aggregate collection belongs to the framework.
Command aggregate lookups belong to repositories; SQLAlchemy searches for read results belong to QueryUseCases. The domain imports
pure Spakky domain bases and mutability declarations, without SQLAlchemy or persistence adapters.

## Request lifetime and SQLite

The CLI process uses `SpakkyApplication.load_plugins().scan(...).start()`.
Default plugin discovery and package scanning register Pods, Tables and Controllers.
Alembic execution modules and the composition root are excluded from scanning. Stateless use cases,
repositories and CLI Controllers use their default scope. Database sessions follow the
current request context and each `@transactional` boundary.

SQLite uses `sqlite+aiosqlite`, `AsyncSessionManager` and `AsyncTransaction`. Use-case and
repository calls are awaited. Owned relationships use `selectin` loading to avoid implicit
synchronous queries during mapping. Migrations run Alembic through an async connection's
`run_sync` bridge. Engine, session and transaction implementations come from Spakky and
are cleaned up on normal and exceptional completion. The CLI disposes the async engine
before the command execution event loop closes.

Git observation finishes before the database transaction begins. The composition root
attaches SQLite policies to the async engine's `sync_engine` events. Writers use `BEGIN IMMEDIATE`;
readers use URI `mode=ro` and `query_only`. All connections enforce foreign keys. There are
no hidden retries. Framework repository not-found/version-conflict errors propagate to the
CLI boundary, which presents host-protocol responses.

Native identifiers are scoped by `(project_id, provider, host_session_id)`.
Re-registration preserves the latest working directory. Linked worktrees and their
subdirectories share a project; independent clones with the same remote remain distinct.
Folder-to-Git promotion preserves IDs, locations and dependent foreign keys without
merging unrelated projects.

## Mapping, versions and ownership

The framework's UUID `version`, `created_at` and `updated_at` are persisted. UUID version
is a domain change token and does not replace the existing integer request `revision`.
SQLAlchemy `version_id_col` uses integer revision to reject stale detached saves and
flush races. Projects receive a storage revision as well.

Result DTOs carry data; use cases compose query results. A frozen result prevents field reassignment without making its domain payload immutable. Returned domain objects are detached from ORM lifetimes, so changing them outside a request does not persist changes.
Timestamps round-trip through UTC. Explicit conversion between SQLite storage and
UTC domain values prevents unchanged timestamps from causing an UPDATE. Same-directory
moves and repeated location association preserve change tokens, timestamps and revisions.

The inherited merge saves Project and its owned location relationship atomically.
Removed values are deleted as orphans. A SQLite trigger rejects reassignment of a
location to another Project, including reassignment attempted by generic merge.
The enclosing transaction rolls back both parent and child changes on failure.

## Schema and preservation

Explicit initialization upgrades through the distributed Alembic head, currently
`core_0005`. `core_0002` adds metadata, project revision and location ownership enforcement;
`core_0003` adds the [source/task ledger](task-ledger.md), and `core_0004` adds [workflow definitions and attempts](workflow-runner.md). Applied revisions remain
unchanged, preserving existing IDs, session revisions, project/location/session values
and dependent foreign keys.

Old rows have no original timestamps, so epoch is an **unknown-time marker**, not a
claim about creation time. Their initial change token is zero UUID; a domain mutation
causes the framework to generate a new token. Newly created aggregates have real
creation timestamps and tokens. Historical records are not promoted to new authority
or successful execution evidence.

Ordinary requests do not migrate storage and reject older or future revisions.
`initialize_database` is the explicit migration boundary. Failure rolls back schema,
rows and revision together. Legacy stores require a separate migration process.

Alembic migration files and its version table define revisions. At the first database transaction, compatibility compares `MigrationContext.get_current_heads()` with `ScriptDirectory.get_heads()` without a separate latest-revision constant.

## Internal request API

```python
from spakky.core.pod.interfaces.container import IContainer
from neurath.application.usecases.get_session_context import GetSessionContextQuery, GetSessionContextUseCase


async def read_session(scope: IContainer, project_id: str, session_id: str):
    # scope is the container of the application bootstrapped by neurath.bootstrap.
    return await scope.get(GetSessionContextUseCase).run(
        GetSessionContextQuery(project_id, session_id)
    )
```

The default path is `$XDG_DATA_HOME/neurath/core.sqlite3`, falling back to
`~/.local/share/neurath/core.sqlite3`. Relative XDG paths are rejected.

## Verification and implementation boundary

Tests exercise inherited methods, actual registry/constructor injection/aggregate
collection, CRUD/batches/deletion, read isolation, no-op saves, stale writes and races,
exception cleanup, ownership conflicts, independent processes, Git/worktree/clone
identity and explicit/concurrent initialization. Migration tests retain original
values and dependent records, repeat initialization and verify full rollback after
migration failure. See [Contributing](../../CONTRIBUTING.md) for running the checks.

[Memory and handoff](memory.md) are implemented. Hook installation, collaboration, remaining business CLI, actual user-data migration
and installation remain subsequent tickets. `setup` rejects installation of this
foundation candidate. Source changes do not alter user databases or installed distributions.

[Task ledger](task-ledger.md) documents the source/correction/attempt/TODO implementation added by #140.

`core_0005` adds [host execution and writer leases](host-runtime.md).

Additional aggregate lookups use `find_by_<criteria>` names. The owned project locations use select-in eager loading (`lazy="selectin"`), not deferred loading. A regression test loads three projects and their locations with one parent SELECT and one child IN SELECT, with no additional SQL on access. Collection joined loading requires `Result.unique()`, which the Spakky 8.2.0 generic get/range methods do not apply. Select-in loading preserves reuse of the framework CRUD implementation.

## Identifiers and immutable input contracts

Internal aggregate IDs and their command, query, and repository references use `UUID`. New IDs use time-ordered `uuid7()`. ORM columns use SQLAlchemy `Uuid()`. Migration `core_0009` converts SQLite key storage to 32-character hex without reissuing UUID4 or UUID7 identifiers. It preserves relational references, composite constraints, indexes, triggers, and unfinished history. Foreign key checks before and after migration protect the transaction; a failure rolls back data, schema, and revision together. External host IDs and strings within JSON, source text, and artifact references retain their original representation. JSON and CLI boundaries render internal UUIDs as canonical strings.

Immutable inputs, results, and observations use Spakky `@immutable` with keyword arguments. This prevents field reassignment without imposing deep immutability on nested collections. Domain value objects retain their framework equality semantics.

## Package and module responsibilities

The [original Ports and Adapters paper](https://alistair.cockburn.us/hexagonal-architecture/) defines the boundary between application internals and external technology; it does not prescribe directory names. Neurath expresses that boundary through these package conventions.

| Package | Owned responsibility |
| --- | --- |
| `domain/aggregates`, `values`, `enums`, `events` | Identity and transitions, values and validation, state distinctions, committed domain events |
| `application/usecases` | One operation per module with its dedicated Command/Query and Result |
| `application/services` | Shared application coordination, such as reconciling monitor scope and current execution |
| `application/ports/repositories`, `services` | External persistence and execution contracts, including response records beside their owning port |
| `infrastructure/models`, `repositories`, `services`, `migrations` | ORM, repository implementations, technical adapters, Alembic revisions |
| `transport/cli`, `events` | Inbound adapters translating CLI requests and committed events into use-case inputs |

Composition, SQLite configuration, external protocols and JSON serialization retain their technical boundary modules. Owned domain values may stay beside their aggregate. Unowned records collections do not belong directly under `application`.

`tools/architecture.py` discovers new files and checks framework component placement, one use case per module, and connectivity of the declaration reference graph. Connected inputs/results/use cases, aggregates/owned values and parent/child mappings may stay together. Common imports, external base types, decorators and docstring mentions do not establish a declaration dependency; shadowing local names do not count as global references. Alembic upgrade/downgrade callbacks define one revision contract. Positive/negative fixtures and real package-scan tests run through shared pre-commit and CI checks. Graph connectivity is a mechanically checkable minimum; semantic responsibility still requires code review.

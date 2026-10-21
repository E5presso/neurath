# Project and session foundation

[Architecture](architecture.md) · [Implementation plan](implementation-plan.md) · [한국어](../ko/core-foundation.md)

#137 manages projects and sessions per request in a user-wide SQLite database.
Dependencies are based on Spakky 8.1.0. `spakky-data`, `spakky-event`, and `spakky-sqlalchemy` are pinned to upstream commit `055fd3ae376a706575e30d1581f0cf1ccb521a54` for post-commit event publishing, in-process setup and request isolation fixes. `uv.lock` installs the same source without local path dependencies.
Public CLI, hooks and installation remain subsequent implementation work.

## Framework components and responsibilities

- `Project` and `HostSession` use `@mutable` and `AbstractAggregateRoot[str]` for identity, equality and change tracking. Project owns `ProjectLocation` as an `AbstractValueObject`.
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

Hook installation, memory, collaboration, business CLI, actual user-data migration
and installation remain subsequent tickets. `setup` rejects installation of this
foundation candidate. Source changes do not alter user databases or installed distributions.

[Task ledger](task-ledger.md) documents the source/correction/attempt/TODO implementation added by #140.

`core_0005` adds [host execution and writer leases](host-runtime.md).

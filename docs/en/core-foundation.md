# Project and session foundation

[Architecture](architecture.md) · [Implementation plan](implementation-plan.md) · [한국어](../ko/core-foundation.md)

#137 manages projects and sessions per request in a user-wide SQLite database.
The foundation uses Spakky Framework 8.1.0 domain and persistence components.
Public CLI, hooks and installation remain subsequent implementation work.

## Framework components and responsibilities

- `Project` and `HostSession` use `@mutable` and `AbstractAggregateRoot[str]` for identity, equality and change tracking. Project owns `ProjectLocation` as an `AbstractValueObject`.
- The existing `id` reference remains a read-only compatibility property over `uid`. Identity selection, folder promotion, ownership conflicts, session scope and movement remain domain rules.
- Repository ports inherit `IGenericRepository`, adding only location-owner and project/provider/native-session lookup.
- `ProjectRepository` and `SessionRepository` inherit `AbstractGenericRepository`. They do not redefine constructors, `get`, `get_or_none`, `contains`, `range`, `save`, `save_all`, `delete`, or `delete_all`.
- Domain tables use `@Table(Domain)` and `AbstractMappableTable[Domain]` with explicit conversion. Owned location records use `AbstractTable` without a separate domain repository.
- `SchemaRegistry` resolves domain/table mappings from Table tags. Repositories do not maintain another mapping registry.
- `ApplicationContext` composes `@UseCase`, `@Repository`, observation Pods and the framework's `ConnectionManager`, `SessionManager`, `Transaction`, and `AggregateCollector`.
- Callers resolve a use case in the request container, open the standard `Transaction`, and invoke `run(command/query)`. Spakky owns commit, rollback and session closure.
- Every use case implements Spakky `ICommandUseCase` or `IQueryUseCase`; inputs inherit `AbstractCommand` or `AbstractQuery`. Each module defines its Command/Query, Result DTO, and UseCase together. The framework result parameter and run return annotation reference that local Result.
- The request boundary maps framework missing-entity and version-conflict errors to `ContextNotFound` and `RevisionConflict`. Use cases ask the domain to validate session/project scope.

SQL for basic CRUD, merge, flush and aggregate collection belongs to the framework.
Local repository SQL implements only the two additional lookups. The domain imports
pure Spakky domain bases and mutability declarations, without SQLAlchemy or persistence adapters.

## Request lifetime and SQLite

Each request owns an independent container, configuration and connection manager.
A module-level `request_config` Pod factory supplies configuration without modifying
process environment variables. Bind configuration in a ContextVar only while constructing
the engine, then restore it; each container receives its own configuration. Register the
framework ConnectionManager directly and apply SQLite policies to its engine. The request
boundary disposes it on normal completion or bootstrap failure. No resident daemon is used.

Git observation completes before the database transaction begins. Writers acquire
`BEGIN IMMEDIATE` before their first read. Readers use SQLite URI `mode=ro` and
`query_only`. Every connection enforces foreign keys; the default lock timeout is
five seconds. There are no hidden retries. Nested independent requests have separate
SessionManagers and transactions.

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
`core_0003`. `core_0002` adds metadata, project revision and location ownership enforcement;
`core_0003` adds the [source/task ledger](task-ledger.md). Applied revisions remain
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
from pathlib import Path
from spakky.plugins.sqlalchemy.persistency.transaction import Transaction
from neurath.application.ports.services.directory_observer import IDirectoryObserver
from neurath.application.usecases.register_session import RegisterSessionCommand, RegisterSessionUseCase
from neurath.application.usecases.get_session_context import GetSessionContextQuery, GetSessionContextUseCase
from neurath.infrastructure.database import initialize_database
from neurath.infrastructure.providers import DatabaseSettings, request_container

path = Path("/explicit/isolated/core.sqlite3")
initialize_database(path)
with request_container(DatabaseSettings(path, write=True)) as scope:
    observation = scope.get(IDirectoryObserver).observe("/project")
    with scope.get(Transaction):
        opened = scope.get(RegisterSessionUseCase).run(
            RegisterSessionCommand(observation, "codex", "native-session")
        )
with request_container(DatabaseSettings(path, write=False)) as scope:
    with scope.get(Transaction):
        current = scope.get(GetSessionContextUseCase).run(
            GetSessionContextQuery(opened.project.id, opened.session.id)
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

Runner, host hooks, memory, collaboration, public CLI, actual user-data migration
and installation remain subsequent tickets. `setup` rejects installation of this
foundation candidate. Source changes do not alter user databases or installed distributions.

[Task ledger](task-ledger.md) documents the source/correction/attempt/TODO implementation added by #140.

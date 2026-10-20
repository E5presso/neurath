# Project and session foundation

[Architecture](architecture.md) · [Implementation plan](implementation-plan.md) · [한국어](../ko/core-foundation.md)

#137 supplies request-scoped project/session persistence. The #154 implementation
was fully rewritten after review: no Core facade, unit-of-work container, structural
Protocol contract, or imperative runtime table mapping remains in the package.

## Responsibilities

- `domain/aggregates/project.py`: mutable Project aggregate owning immutable ProjectLocation values, identity selection, folder promotion, and ownership/conflict rules.
- `domain/aggregates/session.py`: mutable host-session identity, native identifier validation, and movement guarded by the caller's observed revision.
- `domain/observations.py`: immutable primitive filesystem/Git facts, without identity policy.
- `application/ports`: nominal repository and observation ABCs. Repository operations are lookup and storage only.
- `application/usecases`: concrete register-project, register-session, read-context, and move operations with immutable command/query inputs; no use-case interfaces.
- `application/context.py`: immutable result snapshots; entity equality compares identity, while snapshots compare state.
- `infrastructure/models` and `repositories`: declarative records, named conversions, and primitive persistence implementations.
- `infrastructure/database.py`: engine creation, schema verification, and explicit initialization functions.
- `infrastructure/directory_observer.py`: bounded Git/filesystem I/O returning canonical directory/common-directory/primary-worktree facts.
- `infrastructure/providers.py`: Dishka constructor injection with APP engine and REQUEST Session/repository/use-case lifetimes.
- `transport/session_requests.py`: request orchestration and direct `Session.begin()` transaction ownership.

Domain and application layers do not import SQLAlchemy, Alembic, Dishka, or host adapters.
A fresh container is built for every host request; APP scope is a resource lifetime,
not a daemon. Git observation completes before resolving the database session.
Dishka closes the Session and disposes the engine; it never commits a transaction.
Request results are independent immutable snapshots returned after cleanup.

## Internal request API

```python
from pathlib import Path
from neurath.infrastructure.database import initialize_database
from neurath.transport.session_requests import (
    register_session, get_session_context, move_session,
)

path = Path("/explicit/isolated/core.sqlite3")
initialize_database(path)  # Explicit setup; never performed by a normal request.
opened = register_session("/project", "codex", "native-session", database_path=path)
current = get_session_context(opened.project.id, opened.session.id, database_path=path)
changed = move_session(current.project.id, current.session.id, "/project/subfolder",
                       current.session.revision, database_path=path)
```

When the optional path is omitted, all requests use
`$XDG_DATA_HOME/neurath/core.sqlite3`, falling back to
`~/.local/share/neurath/core.sqlite3`. A relative XDG data directory is rejected.
Native identifiers are scoped by `(project_id, provider, host_session_id)` and do
not prove host authority. Re-registration preserves the latest observed directory.
Wrong-project lookups raise `ContextNotFound`; stale moves raise `RevisionConflict`.

A canonical local common Git directory identifies a repository. Linked worktrees
and subfolders share its project; independent clones remain distinct even with the
same remote URL. A folder alias preserves project IDs and dependent foreign keys
when Git is initialized, including a first follow-up from a linked worktree.
Contradictory aliases fail without merging records. Git failures do not silently
become new folder projects.

## SQLAlchemy and migrations

Each request resolves an unpooled engine and actual ORM `Session` through Dishka,
then the request adapter directly uses `with session.begin():`. Writes acquire
`BEGIN IMMEDIATE` before reading mutable state; reads use SQLite read-only mode.
Foreign keys are enabled on every connection. SQLite coordinates competing writers;
the default busy timeout is five seconds and failures are not silently retried.
Repositories flush within the supplied transaction and never commit independently.
Project is the aggregate root; locations have no separate repository or lifecycle.
`get` and `find_by_location` load the complete root and its owned values. `save(project)`
merges parent fields and reconciles the owned ORM collection: existing children stay
attached, new children are inserted, and removed values are deleted as orphans.
Another project's location key conflicts on insertion instead of being reassigned;
the caller transaction rolls back the parent and children together. The schema is unchanged.
All project/session insert and update paths use `save(entity) -> entity`.
`HostSession.move` validates the observed version and changes directory. Primitive
`save(entity)` returns the persisted entity using SQLAlchemy `merge` and
`version_id_col`; the ORM increments the storage version and rejects stale detached
entities. Saving an unchanged path is a no-op under normal ORM dirty checking and retains the version.
There is no repository-side entity cache or load-before-save requirement.

The original `core_0001` DDL and stored table names remain compatible. That revision
now lives in `infrastructure/migrations`; only annotations/docstrings changed.
Explicit initialization refuses legacy tables and applies known Alembic revisions.
Normal requests reject absent or mismatched schemas. Future changes add revisions
and advance `SCHEMA_REVISION`; do not edit previously applied schema definitions.
`tests/fixtures/core_0001.sql` represents the original schema and proves existing
identifiers and revisions remain readable and updatable through the new ORM.

## Validation and limits

Behavior tests cover independent processes, registration/revision races, rollback,
uncommitted read isolation, foreign keys, read-only connections, explicit and
concurrent initialization, old-schema compatibility, rejected legacy-byte
preservation, Git/worktree/clone identity, and folder promotion. The dependent-record
fixture verifies foreign-key preservation; it is not a task or memory feature.

Pure-domain tests exercise root choice, linked-worktree identity, promotion,
conflicting owners, entity identity, and stale movement without Git or SQL. DI tests
verify constructor injection, scope isolation, detached stale saves, repeated saves,
and rollback/connection cleanup on exceptions.

[Required quality checks](../../CONTRIBUTING.md) enforce the concrete review rules
across the entire current package, with negative fixtures. Human review remains
responsible for module cohesion and meaningful documentation.

The old 0.3.1 runtime and implementation-specific tests are recoverable from Git,
not included as a second runtime or a lint exception. This candidate does not
implement tasks (#140), runner (#141), hooks (#142), memory (#143), collaboration
(#144), CLI (#148), legacy conversion (#150), or installation (#151). Their absence
is outstanding implementation work, not completed feature preservation. The wheel
has no obsolete CLI entry point and `setup` refuses installation. No user database,
installed distribution, or real host activation was changed or validated here.

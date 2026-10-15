# Project and session foundation

[Architecture](architecture.md) · [Implementation plan](implementation-plan.md) · [한국어](../ko/core-foundation.md)

#137 supplies request-scoped project/session persistence. The #154 implementation
was fully rewritten after review: no Core facade, unit-of-work container, structural
Protocol contract, or imperative runtime table mapping remains in the package.

## Responsibilities

- `domain/aggregates/project.py`: project identity and `ProjectKind` enum.
- `domain/aggregates/session.py`: host-session aggregate, revision transition, detached context.
- `application/ports`: explicit repository/service/use-case ABCs and immutable command/query inputs.
- `application/usecases`: separate register, read-context, and move implementations with `execute`.
- `infrastructure/models`: declarative ORM records and named `from_domain`/`to_domain` conversions.
- `infrastructure/repositories`: explicit implementations of the application repository ports.
- `infrastructure/database.py`: SQLite engine settings, schema validation, explicit initialization.
- `infrastructure/project_locator.py`: bounded Git observation before opening a transaction.
- `transport/session_requests.py`: direct Session transaction lifecycle and dependency composition.

Domain and application layers do not import SQLAlchemy, Alembic, or host adapters.
Dependencies are constructor arguments, never a generic registry or implicit DI.
The request layer returns immutable domain values and releases its connection before
an external host action. No service retains durable request state in memory.

## Internal request API

```python
from pathlib import Path
from neurath.infrastructure.database import SqliteDatabase
from neurath.transport.session_requests import (
    register_session, get_session_context, move_session,
)

path = Path("/explicit/isolated/core.sqlite3")
SqliteDatabase(path).initialize()  # Explicit setup; never performed by a normal request.
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

Each request opens an unpooled engine and actual ORM `Session`, then uses
`with Session(engine) as session, session.begin():`. Writes acquire
`BEGIN IMMEDIATE` before reading mutable state; reads use SQLite read-only mode.
Foreign keys are enabled on every connection. SQLite coordinates competing writers;
the default busy timeout is five seconds and failures are not silently retried.
Repositories flush within the supplied transaction and never commit independently.

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

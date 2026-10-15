# Request-scoped core foundation

[Architecture](architecture.md) · [Implementation plan](implementation-plan.md) · [한국어](../ko/core-foundation.md)

Issue #137 introduces the new Python core foundation. It does not activate the
redesigned CLI, native hooks, installation, or legacy-data migration. Those routes
remain assigned to the following implementation tickets. Existing 0.3.1 modules
remain temporarily for compatibility and are not used by the new core.

## Storage and request boundaries

`CoreDatabase()` selects `$XDG_DATA_HOME/neurath/core.sqlite3`, or
`~/.local/share/neurath/core.sqlite3` when XDG_DATA_HOME is unset. The path does not
depend on the project or session. An explicit `Path` is available for isolated
installations and tests; transports must share the configured user database.

Initialization is explicit: `CoreDatabase.initialize()` applies the packaged
`core_migrations` Alembic chain to a fresh core database. It refuses to initialize
an existing non-core database; legacy conversion belongs to #150. Normal requests
do not run migrations. Missing or incompatible schema produces `StorageNotReady`.
No implementation test opens the user's installed database.

Each `transaction(write=...)` opens a new SQLAlchemy connection and closes it on
exit. Writes use SQLite `BEGIN IMMEDIATE`, commit together, and roll back together
on failure. Reads open the file read-only and use a read transaction. Foreign keys
are enabled on every connection. SQLite, rather than an in-memory mutex, resolves
concurrent writers. A competing writer waits up to the configured timeout (default
five seconds); lock failures propagate without silently retrying an operation.
Host/network execution must occur outside the transaction.

## Internal API for subsequent tickets

- `neurath.transport.core_requests.build_core(path=None)` composes the same core
  for future CLI and hook adapters. It does not initialize storage or install hooks.
- `Core.open_session(working_directory, provider, host_session_id)` resolves a local
  project and registers an observed session. Repeating registration preserves the
  session and its current working directory.
- `Core.get_context(project_id, session_id)` reads only that project/session pair.
  A session from another project raises `ContextNotFound`.
- `Core.move_session(project_id, session_id, working_directory, expected_revision)`
  updates a session's working directory within its project using compare-and-set.
  A stale revision raises `RevisionConflict`. Session registration cannot silently
  overwrite a later move.

The application layer depends on the `Database`, `UnitOfWork`, `IdentityRepository`
and `ProjectResolver` protocols in `application/core.py`. Immutable values and
errors live in `domain/core.py`. Infrastructure owns SQLAlchemy, Git and Alembic.
`CoreDatabase.transaction()` yields a `CoreUnitOfWork`; future infrastructure
repositories can share its `connection` to commit related records atomically.
Do not store request/session state on the service or retain a unit of work after
returning a result. Add future schema changes to `infrastructure/core_migrations`
and update `SCHEMA_REVISION` with the supported head; do not edit an applied revision.

Host IDs are ordinary scoped identity values, not authentication or permission
proofs. A session is unique by `(project_id, provider, host_session_id)`. The core
records the actual working directory separately from the project identity.

Git projects use the canonical common Git directory. Linked worktrees and
subdirectories share that identity; clones with the same remote URL remain
separate. Without Git, the canonical working folder identifies the project.
A retained folder alias lets later `git init` add a Git identity to the same
project ID without rewriting dependent records. This works even when the first
post-init request comes from a linked worktree. Conflicting recorded identities
raise `ProjectIdentityConflict` rather than merging unrelated data. Git inspection
errors are reported rather than silently inventing a new folder project.

## Verification and limits

`tests/test_core_foundation.py` exercises independent-process persistence,
registration races, stale updates, rollback, uncommitted-read isolation,
foreign-key enforcement, read-only behavior, explicit/concurrent initialization,
Git/worktree/clone identity and non-Git promotion. The promotion test uses a fixture
foreign-key relation to demonstrate dependent-record preservation; it does not
claim task or memory use cases are implemented.

Tasks (#140), workflow runs (#141), host lifecycle/hooks (#142), memory (#143),
collaboration (#144), public Typer commands (#148), migration (#150) and installation
(#151) extend this foundation. Passing isolated core tests is not evidence of live
host enforcement, real message delivery, or completion of the entire redesign.

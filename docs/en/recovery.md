# Migration and recovery

[Documentation](index.md) · [한국어](../ko/recovery.md)

Preserve the existing database and unfinished tasks before changing the active installation. The fresh storage design uses SQLAlchemy and Alembic. Its active database is named `neurath.sqlite3`; do not infer that an older database has been migrated merely because this new file exists.

## Before adoption

Ask the agent to show the intended source and destination, schema versions, backup location, and unfinished-task count. Request a recoverable archive of the complete original database, including data that has no direct equivalent in the new model. Existing data must remain available for inspection and restoration.

> Prepare the migration, preserve the entire original database, and show how each unfinished task will be represented. Leave ambiguous ownership and missing evidence visible.

A valid preparation result explains which records become operational tasks and where all original records remain. It does not silently treat legacy completion flags as current validation evidence or import old text as new human consent.

## Verify the result

Ask for an explicit correspondence between the original unfinished tasks and their new records. Check that prior provenance is retained, task counts are explained, and repeating the migration does not duplicate tasks. Confirm that the original archive can be read before relying on it for recovery.

> Show the migration manifest and unfinished-task mapping. Distinguish preserved original records from records now active in the new model.

The new database may correctly retain work that still cannot advance because ownership, authority, or evidence needs resolution. Preservation does not grant permission to complete it.

## Recover from a storage failure

If the database is unreadable, locked, incompatible, or unavailable, use the installation's emergency bypass to regain control of the host. Bypass must be independent of a healthy operational database. Ask the agent to identify whether bypass is enabled and preserve the failure evidence before attempting repair.

> Enable the database-independent recovery bypass, preserve the affected files, and explain the recovery choices before replacing anything.

Restore only from an identified, checked archive and record which installation will read it. A database whose schema is newer than the installed software must be rejected without modification. Use compatible software or an explicitly prepared restoration; do not force a downgrade by editing version metadata.

Bypass does not complete tasks or verify a repair. After restoring storage, separately check the protocol and actual host activation before leaving recovery mode.

## Retire extra worktrees

Before a checkout is removed, preserve its recoverable contents and a manifest identifying its Git state and local changes. Include necessary ignored content as well as tracked and untracked files. Verify the archive, then remove only the intended checkout.

> Archive the extra worktrees recoverably. Show what was saved and how it can be restored before removing each checkout.

Do not treat a clean-looking working tree as proof that a directory contains nothing worth preserving. Keep recovery artifacts until the preserved work has an agreed disposition.

## What counts as recovery evidence

Recovery reporting should name the preserved original, active destination, migration result, unresolved tasks, verification performed, and restoration path. It should distinguish local tests from live-host observations. Developer procedures and supported command syntax belong in the [contributing guide](../../CONTRIBUTING.md).

## Upgrade callback compatibility

Version 0.3.1 accepts cached hook callbacks using `--host` or no provider argument. The recovery bypass is checked before storage and provider resolution. Outside bypass, an unqualified callback must carry unambiguous provider-specific native envelope metadata; ambiguous input is rejected rather than inventing identity. Newly installed registrations still use explicit `--provider`. This bridge lets an existing turn finish while its host reloads the new registration.

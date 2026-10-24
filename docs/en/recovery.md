# Data migration and recovery

[Documentation](index.md) · [한국어](../ko/recovery.md)

## Current support

The foundation library uses explicit `initialize_database` to initialize/upgrade through the package's Alembic head. See [core foundation](core-foundation.md) for the default DB path, schema and invocation example. Ordinary requests verify compatibility without changing schema.

Initialization does not convert historical harness stores into the new model. Unrecognized existing stores are rejected without modification; current `setup` does not install this candidate. Historical-data conversion belongs to #150, installation cutover to #151 while operational diagnosis, bypass and incident tracking are provided below. See the [implementation plan](implementation-plan.md).

## Preservation during migration and recovery

Subsequent migration must preserve recoverable original databases, required WAL/configuration, unfinished work and sources, then verify their correspondence to the new model. Retain records without direct equivalents for inspection/restoration. Historical completion and ownership records describe past state rather than new success or consent.

[Installation/recovery architecture](architecture.md#9-installation-upgrade-recovery-and-finish-session) defines writer quiescence, incoming-event preservation, cutover and rollback. Verify actual reads/resumption of unfinished work as well as archival. Do not add repeated-input procedures for work already supported by user instructions.

On storage failure, preserve the cause and unfinished work, then regain control through a compatible recovery path. Bypass only suspends harness enforcement; it does not make work successful. Verify actual behavior after repair and disable bypass. Document concrete maintenance commands with their CLI implementation.

Host tools remove worktrees. Preserve unmerged commits, local changes and required untracked/ignored files for the requested targets and verify recoverability.

## Validation

[Acceptance](acceptance.md) A34/A50/A51 cover migration/rollback, A35 owned configuration, A36/A61 fault recovery and A55 requested worktree cleanup. Distinguish temporary-data tests from actual user-installation cutover and activation.

## Operational diagnostics and incidents (#147)

`neurath maintenance diagnose --database <file> --directory <workspace> --provider codex --host-session-id <actual-session>` reads configuration, integrity (including foreign keys), Alembic compatibility, project associations, and resume boundaries separately. It does not create/migrate files or reassociate projects. Missing data is `missing`, failed observations are `failed`, and unobservable boundaries are `unknown`; any such finding returns exit code 1. Stored execution state does not prove actual liveness.

The `maintenance` group can start with a malformed business connection URL. During official application construction only, it uses an unopened read-only SQLite URL, then restores the original environment before diagnosis. It does not edit user configuration files or databases; diagnostics observe the original configuration and selected file.

- `incident open --symptom <symptom> --reference <source> [--project-id <id>]` opens an unresolved incident.
- `incident show --incident-id <id>` reads the original symptom, evidence, transfers, replacement, and revision.
- `incident record --incident-id <id> --revision <revision> --kind reproduction|fix|regression --detail <actual-work> --reference <evidence>` appends evidence in order. Regression requires `--passed` or `--failed`.
- `incident refresh --incident-id <id> --revision <revision> [diagnostic-options]` actually runs diagnostics again and appends the observation.
- `incident escalate --incident-id <id> --revision <revision> --destination <destination-and-reason>` and `incident supersede --incident-id <id> --revision <revision> --replacement-id <id>` preserve unresolved history and original incident links.
- `incident resolve --incident-id <id> --revision <revision> --explanation <resolution>` requires the latest reproduction followed by a fix and passing regression evidence. Resolving an incident does not complete the original task.

When the database cannot save, `maintenance record-failure --detail <cause-and-unfinished-work> --reference <original-call>` appends an independent record to `$XDG_STATE_HOME/neurath/recovery.jsonl` (default `~/.local/state/neurath/recovery.jsonl`). Hook and incident-command failures attempt this path and stderr once each. Failure of both paths does not start retries or model execution. `host_submitted` means output submission; `delivery: unverified` means actual user delivery has not been confirmed. The recovery file does not replace the core ledger or decide success.

## Bypass and restoration verification

`neurath hook handle --provider <host> --bypass` suspends enforcement for that call only. Observable turns, cancellation, and termination continue to be recorded; sources, tasks, and host permissions are not converted into completion or approval. Failed bookkeeping is explicitly reported in the bypass response and an independent recovery record is attempted. Removing the bypass option restores normal enforcement.

After restoration, pass actual host-observed Stop or PreToolUse JSON to stdin of `neurath hook verify --provider <host>`. An actual block through the same normal hook path returns `verified: true` and the response. Normal allowance, invalid input, and database failure do not count as successful verification and return exit code 1. Verification records real lifecycle observations: never fabricate identities or events for an operational session. Actual CLI/SQLite fixture verification does not prove installation or activation in the user's host.

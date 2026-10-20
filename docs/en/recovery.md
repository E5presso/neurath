# Data migration and recovery

[Documentation](index.md) · [한국어](../ko/recovery.md)

## Current support

The foundation library uses explicit `initialize_database` to initialize/upgrade through the package's Alembic head. See [core foundation](core-foundation.md) for the default DB path, schema and invocation example. Ordinary requests verify compatibility without changing schema.

Initialization does not convert historical harness stores into the new model. Unrecognized existing stores are rejected without modification; current `setup` does not install this candidate. Historical-data conversion belongs to #150, installation cutover to #151 and operational diagnosis/bypass to #147. See the [implementation plan](implementation-plan.md).

## Preservation during migration and recovery

Subsequent migration must preserve recoverable original databases, required WAL/configuration, unfinished work and sources, then verify their correspondence to the new model. Retain records without direct equivalents for inspection/restoration. Historical completion and ownership records describe past state rather than new success or consent.

[Installation/recovery architecture](architecture.md#9-installation-upgrade-recovery-and-finish-session) defines writer quiescence, incoming-event preservation, cutover and rollback. Verify actual reads/resumption of unfinished work as well as archival. Do not add repeated-input procedures for work already supported by user instructions.

On storage failure, preserve the cause and unfinished work, then regain control through a compatible recovery path. Bypass only suspends harness enforcement; it does not make work successful. Verify actual behavior after repair and disable bypass. Document concrete maintenance commands with their CLI implementation.

Host tools remove worktrees. Preserve unmerged commits, local changes and required untracked/ignored files for the requested targets and verify recoverability.

## Validation

[Acceptance](acceptance.md) A34/A50/A51 cover migration/rollback, A35 owned configuration, A36/A61 fault recovery and A55 requested worktree cleanup. Distinguish temporary-data tests from actual user-installation cutover and activation.

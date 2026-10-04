# Installation and core transition

[한국어](../../ko/contributing/installation-design.md) · [Core contract](core-v2-spec.md)

The installer plans exact managed file changes, validates a stale plan before writing, and uses a journal for rollback and recovery. User instructions, hooks, permissions, project files and installed skill additions are preserved. Read-only installation planning does not migrate canonical installation metadata.

A v1 transition plan lists retained unfinished Tasks and leases. The final apply requires old project writers to be offline, holds the original SQLite writer lock through adoption and the file switch, and leaves the original database intact. Unfinished Tasks keep their IDs, goals and dependencies in waiting state. Historical reports do not become fresh verification. Completed transition history is not a second live progress ledger. Interrupted installs retain imported obligations and recover managed files through the installation journal.

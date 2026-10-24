# Preserving historical data and resuming selected work

The `migration` CLI inspects historical SQLite read-only, creates a consistent copy, and connects selected records to the current user-wide core. Reading or registering a snapshot does not turn unfinished historical tasks into current session work or Stop blockers. Historical owners, sessions, leases, and results remain history; they do not establish current native identity or authority.

## Inspection and preservation

```sh
neurath migration inspect --source /path/to/old.sqlite3
neurath migration prepare --source /path/to/old.sqlite3 \
  --directory /path/to/project --archive-directory /path/to/private-backups \
  --config /path/to/old-config.json
neurath migration read --archive-id UUID --section tasks --limit 20
```

`inspect` returns actual tables, row counts, and WAL presence. Recognized formats contain either `records/tasks/source_archives` with Alembic `0001/0002`, or `runtime_records/runtime_schema/events`. Other formats are explicitly `unknown`. `prepare` uses SQLite backup for a consistent committed view and separately preserves observed original DB/WAL/SHM files and selected configuration files. `files.json` distinguishes these raw copies from the consistent query snapshot. The same source path, contents, and configuration resolve to the same registration.

Read sections are `tasks`, `sources`, `workflows`, `enclave`, `messages`, `learning`, `memory`, and `unknown`. Original content, status, and references remain intact. `unknown` lists preserved tables and row counts; it does not claim complete semantic interpretation. Embedded `zlib-json-v1` archives decompress incrementally to a temporary file and expose selected rows without loading the entire JSON into memory. `total: null` means the full count has not been established. Follow `next_offset` using the same section and `--offset`. Only an exhausted page reports the observed total.

## Connecting current work

```sh
neurath migration resume --archive-id UUID --key ORIGINAL_TASK_KEY \
  --workflow-key ORIGINAL_WORKFLOW_KEY
neurath migration recall --archive-id UUID --section messages --key ORIGINAL_MESSAGE_KEY \
  --task-id CURRENT_TASK_UUID
```

The agent reads original requirements and status, then selects work within the existing user request. No new human approval or reentry of the original request is required. `resume` starts unfinished work in the actually observed current project and session. A handoff memory retains the old definition, status, and ownership. Lineage reconciles runtime tasks already represented by the record store, preventing duplicate current tasks. Repeating resumption returns the same task. Unfinished historical phases continue as host phases in the existing runner; historical success is not a successful current attempt. Previously successful prerequisites retain their original records and evidence and require a mandatory first runner phase to verify current validity; no successful current task is fabricated. Resume unfinished prerequisites first, then the dependent task references those same current tasks and remains pending until they succeed. Missing prerequisites or unrecognized dependency identifiers produce an explicit error and remain preserved.

`recall` connects selected sources, workflows, enclave data, messages, learning, and memories through existing Memory records and enclave assumption references. It does not promote historical facts to verified current facts, messages to read/ACK, or proposed lessons to applied improvements. Read their original status and references, then continue through the existing work, collaboration, and retrospective paths. Unknown original content and unstructured data are not guessed into new user instructions.

## Writer cutover and events

```sh
neurath migration fence --source /path/to/old.sqlite3 \
  --archive-directory /path/to/private-backups
```

This changes the selected path and is intended for an actual cutover. POSIX `lsof` observes external SQLite connections; the service checks changes since the snapshot and obtains a SQLite exclusive lock. Failed observation, open connections, or a late change prevents path switching. After preserving a consistent snapshot and the original inode, an atomic replacement points the original path at a transition directory, rejecting standard SQLite reconnection writes. Late open handles also fail SQLite's moved-database write check. This establishes a technical barrier for that SQLite path; it does not prove host process termination, external schedule cancellation, or cessation of programs using arbitrary other paths.

When the current hook CLI encounters that transition path, it durably queues both the original payload and normalized event with locking and fsync. This introduces no new approval gate for ordinary tools. Stop events preserve their original payload and pending state, suspend harness enforcement, and return control to the user. Repeated Stop events neither block termination nor request another recovery turn, and never record task completion. After recovery, `migration replay --directory TRANSITION_DIRECTORY` applies events in order through the existing `ReceiveHook` transaction and acknowledges each after commit. Interruption before the acknowledgment file update does not duplicate an event. Actual host delivery remains `unverified`. Monitor ticks remain explicitly pending with an error instead of becoming new user requests; they require reconciliation of current schedule, cancellation, and ownership through the existing monitor path before claiming application.

## Recovery after new records

```sh
neurath migration recover --source /path/to/current-core.sqlite3 \
  --destination /path/to/recovered-core.sqlite3
```

`recover` checks current Alembic compatibility and copies the entire current core to a new destination. It never overwrites an existing destination and returns `activated: false`. It does not down-convert to an old database while discarding new tasks, memories, or applied-event records. Keep transition queues, snapshots, and original files together, select a compatible core, and replay pending events. Copy creation, configuration switching, and actual host activation are separate operations.

Regression tests cover synthetic original content, order, lineage, selective resumption, actual SQLite reconnection and late handles, WAL and observation failure, real hook CLI queuing and replay deduplication, and recovery with new records. Copies of actual historical data also verify reading, resumption, recovery, and bounded large-data queries. These checks do not establish production cutover, host schedule cancellation, or actual model delivery.

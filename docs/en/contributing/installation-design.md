<!-- date: 2026-09-13; synced_from: 655c8768709e59b5e5012bab0adc4d888e3e7fa5 + current working-tree facts -->

# File ownership, transactions, and shared-state cutover

[한국어](../../ko/contributing/installation-design.md)

The installation engine must add a working harness without taking ownership of the surrounding application. It therefore models each managed path as an observed before-state and a proposed after-state, and retains enough private information to reverse a known operation. File placement, canonical installation state, and native runtime activation remain separate responsibilities.

## Project the host integration

| Target | Managed contribution | Existing content |
| --- | --- | --- |
| `AGENTS.md` | Marked instruction block | Surrounding bytes and block placement preserved |
| `.agents/skills/<name>` | Shared/Codex skill projection | Unowned name collisions rejected |
| `.codex/hooks.json` | Command hook groups | Other groups preserved |
| `.codex/config.toml` | Neurath MCP configuration | User configuration and inline hooks preserved |
| `CLAUDE.md` | New symlink to `AGENTS.md`, or import block in a regular file | Existing regular-file content preserved; conflicting links rejected |
| `.claude/skills/<name>` | Link to `../../.agents/skills/<name>` | Unowned links and names checked |
| `.claude/settings.json` | Claude hook groups | Permissions, model preferences, and other groups preserved |
| `.mcp.json` | Claude MCP server entry | Other servers preserved; reserved-name collisions rejected |

A generic profile supplies common rules and empty project-specific binding slots. It does not choose the target's framework, test runner, model, sandbox, or approval preferences. The installer merges its known pieces and refuses configurations whose managed part cannot be isolated safely. Existing inline Codex hooks can coexist with `.codex/hooks.json`; the host may load both and warn, and diagnostics report that condition.

Managed blocks in `AGENTS.md`, a regular `CLAUDE.md`, and `.gitignore` allow edits around the block. A changed block, missing separator whose ownership is ambiguous, or changed owned configuration produces a conflict. A user-edited project binding is deliberately released from installer ownership before later update or uninstall processing.

The common hook events are `SessionStart`, `SessionEnd`, `SubagentStart`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `PreCompact`, `Stop`, and `SubagentStop`. Claude additionally receives `PostToolUseFailure` and `PermissionDenied`. Codex `SessionEnd` has a three-second command timeout. Neurath invokes its own handlers sequentially within one hook command; existing external hook groups retain the host's concurrency behavior. Installation does not introduce model, sandbox, or approval preferences.

## Freeze a plan before writing

[The transaction engine](../../../src/neurath/install/transaction.py) computes a plan containing a schema version, canonical target root, distribution identity, action, profile, hosts, prefix, before/after installation state, checked paths, and ordered changes. Each change retains before/after file bytes, modes, or link targets. Parent paths are observed too, so a symlink introduced after planning cannot redirect a reviewed write.

The plan ID is a digest of canonical plan content. Plans are private: raw plans can contain original credentials or project configuration. [Plan storage](../../../src/neurath/install/plan.py) creates non-overwriting files with mode `0600`, normally below the Git administrative `neurath-plans` directory. Existing destinations and symlink outputs are rejected. The MCP layer exposes an opaque session-artifact reference and a path/action summary, bound to the native actor and target. A plan prepared by another actor or for another worktree is unavailable to the caller.

## Apply under a lock and retain recovery state

Application takes the installation lock and checks for unfinished journals. It then compares all observed paths, recomputes the plan with the current distribution, and requires exact equality. A stale target, modified plan, or changed distribution stops before application. An empty change set returns the plan ID with zero changes.

For a nonempty plan, the installer begins a durable journal, checks each path again immediately before mutation, and uses atomic path replacements. If an error interrupts writes, it reverses already-applied changes whose contents still match the known after-state. Concurrent edits are retained. A rollback conflict keeps the journal so supported recovery can inspect it later. On successful completion, installation state and record are finalized and eligible empty skill directories are pruned.

Canonical installation state and records use the shared runtime database through [InstallStateStore](../../../src/neurath/install/state_store.py); the target's state file is a validated projection. Private plan files and recovery originals remain feature-specific artifacts. A projection that disagrees with canonical state is an error, not an alternative authority.

## Select recovery from the observed state

| Condition | Result and next step |
| --- | --- |
| Checked file or parent changed since planning | `stale plan`; preserve changes and prepare again after resolving intent |
| Plan target/distribution/content differs | Reject application; obtain a plan from the correct target and runtime |
| Managed block, skill, server entry, or link was edited | Ownership conflict; inspect the specific path before deciding how to reconcile |
| Interrupted installation journal exists | `installation-recovery-required` through MCP; run `installation_recover`, inspect diagnostics, then replan |
| Recovery path matches neither recorded before nor after | Recovery conflict; preserve that path and journal for explicit reconciliation |
| Restore ID is missing, corrupt, or from another target | Reject restore; identify the actual installation record |
| Completed-operation restore sees a changed after-state | `restore conflict`; do not overwrite the later change |

`restore` reverses a completed installation operation using its record. `recover` rolls an interrupted operation back to its known before-state. Neither is a general reset of the repository. Installation records retain exact source originals privately, including file modes and links. A successful restore uses the retained prior runtime where recorded; deleting runtime environments independently can remove that capability.

## Retire legacy shared database writers explicitly

Mutable runtime state is canonical in `.neurath/local/runtime.sqlite3` under the Git-common-derived control root. Linked worktrees share that database; independent clones and computers do not automatically share it. Domain namespaces and codecs preserve task, ownership, message, memory, and installation semantics within the shared store.

Importing a retained legacy database stages data. It does not retire an old process that can still write to the old location. A dormant linked checkout can also launch an old writer later. The [cutover service](../../../src/neurath/install/cutover.py) therefore inspects the four declared SQLite sources, import guards, and all linked-worktree launchers before retiring legacy paths.

The bootstrap diagnostic path is available independently of normal runtime initialization:

```sh
neurath --root /absolute/path/to/project cutover inspect
neurath --root /absolute/path/to/project cutover prepare
```

`inspect` returns status, blockers, sources, launchers, digests, and a token describing the observed state. `prepare` imports only when the canonical database is absent; otherwise it inspects. Stop the relevant database writers before preparation or application. Open SQLite handles, unfinished journals, unknown or modified launchers, changed guards, and unsupported late rows block retirement. Handle inspection requires Unix `lsof`.

After reviewing a ready inspection and stopping writers, use that exact returned token:

```sh
neurath --root /absolute/path/to/project cutover apply --expected-token TOKEN_FROM_INSPECTION
```

The service temporarily fences known generated launchers, stores private backups, and replaces old SQLite file locations with directory tombstones. Guards and audit state are updated transactionally while preserving canonical application data. New messages, changed bodies or recipients, and unsupported changes are rejected; only supported lifecycle differences against terminal canonical message records can be reconciled. Permanent tombstones prevent an old runtime from reopening legacy database files. Launchers are restored afterward, and affected worktrees are identified for supported runtime updates.

If interrupted, use:

```sh
neurath --root /absolute/path/to/project cutover recover
```

Recovery restores precommit paths or completes postcommit launcher restoration according to the durable journal. Conflicting files and damaged backups are preserved and reported. Installation stays blocked while the cutover journal remains. After affected worktrees are updated, verify placement, protocol, and actual native activation separately. Cutover itself does not certify host activation.

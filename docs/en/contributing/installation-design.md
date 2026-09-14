<!-- date: 2026-09-14; synced_from: 243400e58ca74c7fd79bcdd86b488953fa743b97 -->

# How installation preserves a project's work

[한국어](../../ko/contributing/installation-design.md) · [Install walkthrough](installation.md)

The installer must add a working agent harness to an existing project without losing the project's instructions, hooks, dependencies, or later edits. It does this by preparing an exact change, checking that the target still matches, and retaining enough information to reverse the change. These mechanisms are shared by installation, updates, uninstall, and restore.

## One package, several owned surfaces

Neurath's executable source and bundled assets live under `src/neurath`; `src/neurath/_assets` is the independent asset source. Installed skills and rules are projections: generated versions adapted to the target's public names, host configuration, and project bindings. They are not the development source.

| Surface | Installation behavior |
| --- | --- |
| `AGENTS.md` | Adds a marked Neurath block while preserving surrounding instructions. |
| `CLAUDE.md` | A new file can link to `AGENTS.md`; an existing regular file receives a managed import. |
| `.agents/skills` and `.claude/skills` | Installs selected public skill names and shares them with Claude through managed links. |
| `.neurath/policy.md`, `.neurath/rules`, `.neurath/reference` | Projects portable policy, rules, contracts, and references. |
| `.neurath/project.json` | Initializes missing bindings; preserves subsequent user changes. |
| Host hooks and MCP settings | Adds Neurath entries while preserving existing groups and unrelated settings. |
| `.neurath/run` | Executes an absolute interpreter with isolated Python imports. |

Codex uses `.codex/hooks.json` and `.codex/config.toml`; Claude uses `.claude/settings.json` and `.mcp.json`. Existing inline Codex hooks remain, and diagnostics can point out that the host loads both formats. The installer does not select a model, sandbox, or approval preference for the user.

Hooks cover session start/end, subagent start/stop, user prompt submission, pre/post tool use, compaction, and Stop. Claude also receives tool-failure and permission-denial events. Installed command timeouts are 30 seconds except Codex SessionEnd, which uses 3 seconds; Neurath handlers within one command execute sequentially. Hook registration is installation evidence. An actual host event is needed to establish activation.

## Review a change before it becomes a transaction

A plan records the resolved worktree root, distribution identity, selected profile/hosts/prefix, observed paths, and before/after file contents, modes, or links. Its identifier is a digest of the plan. A **receipt** is the retained record of that installation operation; its ID supports later restore.

Native administration exposes an opaque `plan_ref` and a path/action summary through `installation_plan`. Original file contents stay in a private plan file. `installation_apply` accepts a plan prepared for the same actor and worktree. See [exact inputs](setup-reference.md#administer-an-installed-worktree).

Private plan files may contain original configuration and credentials. `write_plan` publishes a complete mode-`0600` file without replacing an existing file or symlink. The default private plan directory uses mode `0700`. This is why a change summary belongs in a report while the full plan belongs in private state.

Apply takes an installation lock, checks the observed target again, and regenerates the expected plan from the current distribution. It journals the transaction before replacing files. It also rechecks each path immediately before writing. An unchanged repeated install returns `changed: 0`.

If a write fails, rollback restores a path only while it still equals the planned before or after state. An unrelated edit is preserved and leaves a recoverable conflict. `stale plan`, `stale or modified plan`, and `concurrent change` identify different points at which that comparison failed.

## Distinguish project edits from managed edits

An edit outside a Neurath instruction block can be preserved on update or uninstall. An edit inside the owned block, an altered managed hook/server setting, or a modified installed skill requires an explicit resolution. The installer will not infer that its old version should replace the new bytes.

A project binding is deliberately editable: `.neurath/project.json` survives update and uninstall after the user changes it. Uninstall restores retained originals and removes owned additions where current state permits. Restore reverses a selected installation record, rather than choosing an arbitrary older package. A prefix is part of installation identity, so an installed prefix change requires uninstall first.

## Understand private state before recovery

Canonical mutable runtime state resides in `.neurath/local/runtime.sqlite3` beneath the Git-common-derived control root. Linked worktrees share that database, with separate roots, namespaces, codecs, revisions, and digests retaining the meaning of each record. Separate clones or computers do not synchronize merely because their repository names match.

Installation states, journals, and receipts are canonical SQLite records. `.neurath/install.json` is a schema-2 reference projection containing `authority: "reference-only"`, a `state_ref`, and a digest; editing it does not rewrite canonical installation state. Plans, restoration originals, and private process artifacts still use purpose-specific files. A shared database does not imply every private file moved into it.

`installation_recover` reverses an interrupted journal after verifying that every affected path is still a known before/after value. A path with other bytes produces `recovery conflict`. Preserve those bytes and inspect the journal and current target before further work. There is no safe interpretation in which that error authorizes overwriting the concurrent edit.

## Retire legacy SQLite sources deliberately

Importing legacy state and preventing an old process from writing it again are separate steps. A shared-store cutover is the explicit retirement procedure for retained legacy databases and launchers, including dormant linked worktrees.

Stop the relevant writers and close SQLite handles before using the bootstrap sequence:

```sh
neurath cutover inspect
neurath cutover prepare
neurath cutover inspect
neurath cutover apply --expected-token RETURNED_INSPECTION_TOKEN
```

Use `prepare` when initial legacy import must be staged; inspect again afterward and apply only the returned, reviewed token. The procedure requires Unix `lsof` and rejects open handles, journals, unknown launchers, changed guards, and unrecognized late rows. It temporarily fences known launchers, retains originals, replaces legacy database paths with directory tombstones, and commits canonical guards and an audit record.

For interruption, `neurath cutover recover` restores originals before commit or finishes launcher restoration after commit. Changed paths or damaged backups remain explicit recovery errors. After retirement, update affected worktrees through supported installation and observe placement, protocol, and native activation separately. The ordinary installer stops with an explicit cutover-required error while this prerequisite is unresolved.

Source: [transaction engine](../../../src/neurath/install/transaction.py), [private plans](../../../src/neurath/install/plan.py), [state store](../../../src/neurath/install/state_store.py), [cutover](../../../src/neurath/install/cutover.py). Tests: [transaction preservation](../../../tests/test_installer.py), [installation tools](../../../tests/test_installation_tasks.py), [cutover compatibility](../../../tests/test_install_cutover_compatibility.py), [shared state](../../../tests/test_sqlite_install_maintenance.py).

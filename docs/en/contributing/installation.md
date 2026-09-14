<!-- date: 2026-09-13; synced_from: 655c8768709e59b5e5012bab0adc4d888e3e7fa5 + current working-tree facts -->

# Install and maintain a project integration

[한국어](../../ko/contributing/installation.md)

An installation connects project instructions, skills, hooks, and the named MCP server to an isolated Neurath runtime. The installer preserves project-owned configuration and records its own changes so updates, removal, and restoration can reason about exact prior state. The human-facing onboarding is in [installation usage](../usage/installation.md); the commands below are agent execution references.

## Choose the entry point

A target without Neurath cannot use its MCP server to bootstrap itself. From an intact Neurath source checkout, an agent can run:

```sh
./setup /absolute/path/to/your-project
```

The target must be a Git worktree root. If the requested target is a new directory, initialize its Git repository as part of the authorized setup. Git must already be available. The source launcher can obtain `uv`, provision Python 3.14, build Neurath's wheel, and install it into a persistent tool environment. See [setup options and effects](setup-reference.md).

The first installation defaults to the `generic` profile and both supported hosts. A later installation preserves the installed profile, hosts, skill prefix, and user-edited bindings unless explicitly changed. To install only one integration:

```sh
./setup /absolute/path/to/your-project --host codex
```

Use `--host claude-code` for Claude Code. A name prefix can avoid an existing project skill name:

```sh
./setup /absolute/path/to/your-project --skill-prefix neurath-
```

For example, the public `debug` skill becomes `neurath-debug`. Existing user skills keep their names. A prefix resolves directory names; overlapping hooks and state ownership with another harness still require checking which harness owns each responsibility. Changing an installed prefix requires uninstalling the existing integration first.

## Plan and apply inside an active installation

An authenticated agent with the required worktree ownership uses `installation_plan`, then passes its returned reference to `installation_apply`. Both use the same transaction engine as bootstrap. A plan is bound to this actor, worktree, distribution, and observed files. Preparation returns paths and actions without exposing original file content.

Example input to `installation_plan`:

```json
{"action":"update","key":"project-update-plan-1"}
```

Read `result.plan_ref`, `result.plan_id`, `result.action`, and `result.changes`. Apply the exact authorized plan using the returned reference:

```json
{"plan_ref":"<returned plan_ref>","key":"project-update-apply-1"}
```

The angle-bracket text is a substitution marker, not a valid invented reference. Host identity is supplied by the native integration; copying identity fields from another invocation does not authenticate this call. Preserve a stable key for the same request and use a new key when the intended operation changes.

The planning action can be `install`, `update`, `uninstall`, or `restore`. `profile` accepts `generic`; `hosts` accepts `codex` and `claude-code`; omitted options preserve installed selections. Restoration additionally needs the actual `installation_id` of the operation to reverse. Application returns an installation record ID and changed-path count. A repeated unchanged installation can return `changed: 0`.

The input objects are closed: undeclared fields are rejected. `key` is required and contains 1–512 characters. The apply reference contains 1–71 characters, `installation_id` is at most 64, and `skill_prefix` is at most 128 before its prefix syntax is validated. `hosts` has at most two entries. Tool envelopes contain `ok` and `operation`, plus a structured `result` or an `error` with `code`, `message`, `state`, `retryable`, and `next_action`. A plan lookup can report `plan-unavailable` for the wrong actor or target, `invalid-plan-reference` for unsafe stored paths, and `plan-changed` when private content differs. Read the reported recovery action before retrying.

## Read the installation result correctly

Use `diagnostics_integrity` for the distribution and `diagnostics_project` with `{"protocol":true}` for project checks. These are distinct observations:

| Observation | What it establishes |
| --- | --- |
| Distribution integrity | Packaged files match the manifest |
| Placement | Installed bytes and links match the installation record |
| Protocol | Isolated subprocess fixtures accept startup input and reject malformed input |
| Native activation | The actual host loaded and executed the integration in a real session |
| Target check | The actual project's configured check ran with its observed outcome |

`placement: passed` and protocol success do not establish live activation. Setup can finish applying files and then report failed diagnostics; inspect the returned installation record and diagnostics rather than treating that as a wholly unapplied operation. A fresh host session or tool catalog reload may be needed. The agent handles project configuration and explains any required user trust or authentication action.

## Preserve edits through maintenance

Updates and uninstall preserve user instructions outside intact managed blocks. The same applies to shared hook and MCP configuration that can be safely separated from Neurath's entries. Changes inside a managed block or owned skill stop the operation with a conflict. The installer does not solve conflicts by overwriting the current contents.

Once the user edits `.neurath/project.json`, its bindings remain project-owned across update and uninstall. Removal may leave history or empty directories; it removes managed integration, rather than deleting arbitrary project state. Other projects continue using the runtime recorded by their installation when this project's runtime changes. Previous runtimes remain available for supported restoration.

For an interrupted journal, call `installation_recover` with a stable key, then inspect project diagnostics before making a new plan. Recovery restores recorded before-state only while current paths match one of the journal's known states. An independently edited path produces a recovery conflict and is preserved. For a completed operation, prepare a `restore` plan using its installation ID; this reverses that recorded operation rather than selecting an arbitrary version.

Stale plans, modified owned files, unknown symlinks, and partial transactions each require diagnosis. The [transaction design](installation-design.md) gives exact failure and recovery boundaries. Official new-version offers have an additional exact-offer choice contract described in [release updates](releases-reference.md).

Implementation: [transaction engine](../../../src/neurath/install/transaction.py), [MCP installation operations](../../../src/neurath/runtime/installation_tasks.py), [installer tests](../../../tests/test_installer.py).

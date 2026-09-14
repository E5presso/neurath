<!-- date: 2026-09-13; synced_from: 655c8768709e59b5e5012bab0adc4d888e3e7fa5 + current working-tree facts -->

# Own and package the runtime assets

[한국어](../../ko/contributing/assets.md)

The installed harness must run independently of its source checkout and independently of the application it supports. Neurath therefore owns its distributable runtime assets under `src/neurath/_assets`. The target receives projections and launchers that refer to a separately installed tool environment. Another repository is never a build input.

## Choose the source of a change

| Area | Responsibility |
| --- | --- |
| `src/neurath/_assets` | Independently executable rules, skill resources, and harness engines |
| `src/neurath/install/projection.py` | Host-neutral projection and host-specific installation contributions |
| `src/neurath/runtime` | Named task contracts and domain-operation dispatch |
| `src/neurath/hosts` | Actual host lifecycle and identity integration |
| `src/neurath/resources.py` | Package resource location and distribution identity |
| `src/neurath/manifest.json` | Expected package file digests |
| `tests/runtime` | Runtime contracts executed against a disposable standalone corpus |

Edit the package source, then regenerate and check the manifest. Installed `.agents/skills`, Claude skill links, `.neurath/rules`, and launchers are installation outputs. Directly editing an owned projection makes the installed state diverge from its record and can block update or uninstall.

The `generic` profile supplies common behavior. Project-specific document roles, test commands, vocabulary, and metadata conventions belong to the target's instructions and `.neurath/project.json`. The package does not embed a private application's terminology, source paths, or dependencies to make its runtime work.

## Understand the public surface

The current surface contains 31 public skills. Twenty-nine have phase contracts; `explain-code` and `graphify` are supporting skills without those contracts. A public skill name and its internal contract identifier serve different roles; a configured prefix changes the public projection name without renaming the internal contract.

The named stdio MCP API exposes 127 operations from 137 internal operations. Closed input schemas reject undeclared fields, and structured responses separate results from failures. Saved-call compatibility dispatch is not public discovery: `workflow_start`, `workflow_advance`, and `workflow_finalize` remain accepted for stored calls while new explicit phase workflows use `phase_start`, `phase_complete`, and `phase_finalize`. The legacy arbitrary-argument and material/verification bookkeeping paths are also compatibility infrastructure, rather than an ordinary agent execution interface.

The current [task schema](../../../src/neurath/runtime/task_schema.py) and [MCP server](../../../src/neurath/agents/mcp.py) define that surface. Use their named operations and actual returned revisions; do not add a CLI string, Python module, or direct state-editing gateway as a second routine interface. Ordinary project file edits and commands run through the host's normal tools.

## Preserve package integrity and runtime independence

[Resource handling](../../../src/neurath/resources.py) locates `_assets` inside the installed package. Distribution identity hashes package-relative paths and file bytes, excluding Python cache artifacts. The [manifest builder](../../../tools/build_manifest.py) records file integrity expected by diagnostics. A stale manifest is a source/package mismatch and must be regenerated after changing executable assets.

The development sequence for a runtime change is:

```sh
uv run --locked python tools/build_manifest.py
uv run --locked python tools/check.py
uv build
./setup --self
```

`uv run --locked python -m build` is another available build entry point. The built package, installed runtime, and native loaded instance are different artifacts. Keep the actual wheel identity in private validation results when correlating those observations.

Installed launchers use an isolated Python import path. A target application package named `scripts` must not shadow the bundled engine. Wheel validation imports bundled modules in a fresh external environment while denying access to the source checkout. Setup validation also moves the original source away before exercising the installed launcher. These checks substantiate independent packaging; the native-host scenarios in [validation](validation.md) establish actual host behavior separately.

## Keep mutable state outside the corpus

The canonical database for mutable runtime domains is `.neurath/local/runtime.sqlite3` under the Git-common-derived control root. Linked worktrees share this root while namespaces and domain codecs keep ownership, revisions, messages, task truth, memory, and installation state distinct. Independent clones or computers have no automatic synchronization.

This database does not make every private file interchangeable. Immutable installation plans, retained originals, recovery backups, and diagnostic artifacts have their own formats and lifecycles. Installed configuration projections also remain on disk. Preserve these distinctions when adding a state domain or documenting a storage migration. [Installation design](installation-design.md) describes explicit legacy-writer retirement.

Session state access is mediated by the session kernel and caller-bound state handle. Worktree leases and fencing tokens exclude stale writers. A caller-supplied session ID or an artifact string is not a replacement for native host identity. Package assets must retain this boundary when exposing new operations.

## Verify publication contents

Public documentation has matching English and Korean paths and is included in the source distribution. Package and publication tests verify metadata, locale links, path conventions, independence, and exclusion of private artifacts:

```sh
uv run --locked pytest -q tests/test_publication.py
```

Do not package raw host transcripts, installation originals, receipts, personal paths, credentials, private project names, or debugging fixtures. Keep those in ignored storage such as `.validation`. Public examples should be generic and reproducible using only Neurath-owned resources. `neurath corpus /path/to/new-directory` copies those standalone resources into a new directory for inspection.

Sources and checks: [package metadata](../../../pyproject.toml), [publication tests](../../../tests/test_publication.py), [distribution validation](../../../tools/validate_distribution.py), [runtime fixture runner](../../../tools/run_core_regressions.py).

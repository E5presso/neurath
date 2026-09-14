<!-- date: 2026-09-14; synced_from: 655c8768709e59b5e5012bab0adc4d888e3e7fa5 + current working-tree facts -->

# Develop and verify Neurath

[한국어](../../ko/contributing/index.md)

Neurath installs a shared harness into an existing Git project. Work on Neurath changes the installer, its independently packaged runtime, or the contracts that connect Claude Code and Codex to project work. Work on an application using Neurath belongs in that application's source and project bindings. For that workflow, begin with the [usage guide](../usage/index.md).

This section provides execution references for agents developing and operating Neurath. It explains where to change behavior, which checks establish which results, and how an authorized installation reaches a target project.

## Find the change boundary

| Intended change | Source to inspect | Reference |
| --- | --- | --- |
| Preserve or project project files differently | `src/neurath/install/` and installer tests | [Installation transaction design](installation-design.md) |
| Change startup, setup options, or runtime selection | `setup`, `src/neurath/cli.py`, `src/neurath/install/setup.py` | [Bootstrap and setup](setup-reference.md) |
| Change bundled rules, skills, or engine behavior | `src/neurath/_assets` and corresponding runtime tests | [Packaged assets](assets.md) |
| Modify authenticated task operations | `src/neurath/runtime/task_schema.py`, domain task modules, `src/neurath/agents/mcp.py` | [Task tools](task-tools.md) |
| Change host activation or caller identity | `src/neurath/hosts/identity.py`, `src/neurath/hosts/hooks.py` | [Validation](validation.md) |
| Change official update preparation or recovery | `src/neurath/updates.py`, `src/neurath/release_install.py` | [Release updates](releases-reference.md) |

The package supports macOS and Linux with Python `>=3.14,<3.15`. POSIX process groups, `fcntl`, and Bash are part of its operating assumptions; Windows is outside the supported platform contract. The runtime declares `claude-agent-sdk>=0.2.152,<0.3`. Target projects may use another language and retain their own dependency environment. The package metadata is in [pyproject.toml](../../../pyproject.toml).

For the strategy behind periodic goal context, read [design principles](design-principles.md) and [runtime delivery](runtime-lifecycle.md). [Provider continuity](provider-continuity.md) covers retaining target-native settings and adopting another provider's interrupted work; it separates context retrieval, task transfer, and source resumption fencing.

## Prepare a reproducible development environment

Run from the Neurath checkout:

```sh
uv sync --locked
```

This creates or updates the development environment from the committed lockfile. It does not install the harness into a target project. For a new installation behavior, first add a test that fails for the intended before/after case. Start with the relevant test; once the implementation is stable, run the required check:

```sh
uv run --locked python tools/check.py
```

The check executes package integrity, Python diagnostics, package and installation tests, and runtime contracts in a disposable Git fixture. Its success applies to the source tested. [Validation](validation.md) describes distribution, bootstrap, and native-host checks that establish additional facts.

For a runtime or asset change, regenerate package integrity data before checking and building:

```sh
uv run --locked python tools/build_manifest.py
uv run --locked python tools/check.py
uv build
./setup --self
```

Self-installation updates the harness used by this checkout through the normal installer. Its persistent tool environment is separate from development `.venv`; record build output and installed runtime separately. A documentation-only change does not require self-installation solely to deliver new prose.

## Maintain the product contract

Edit managed runtime sources under `src/neurath/_assets`. Installed `.agents/skills` and `.neurath/rules` are projections and will be checked against the installation record. Editing a projection directly creates an installation conflict rather than a reusable source change.

Public detailed documents use matching relative paths below `docs/en` and `docs/ko`. Each locale's `usage` explains natural-language requests and user-visible outcomes; `contributing` contains execution and configuration examples. Keep both locales equivalent in scope, supported behavior, errors, and limitations. Navigation stays in the reader's language except the reciprocal language link. Only root README and CONTRIBUTING entry points use `.md` / `.ko.md` pairs.

For a public documentation change, the focused convention check is:

```sh
uv run --locked pytest -q tests/test_publication.py
```

Public packages and documentation must not contain private source originals, installation plans, diagnostic logs, receipts, credentials, personal paths, or provenance from other repositories. Store evidence in ignored private storage such as `.validation`. The [asset reference](assets.md) explains distribution ownership and inclusion.

## Describe the result for a reviewer

Explain the concrete trigger, changed behavior, compatibility or installation impact, and actual checks performed. Link relevant source and tests. State whether the evidence concerns source integrity, built-package execution, target placement, protocol simulation, or a real native session. An authenticated owner task result records the owner's outcome; explicit review workflows have their own independent reviewer contracts.

Use current operation results and revisions when working through named MCP tasks. Ordinary native edits and commands do not require a separate material batch or per-criterion acceptance document. The task ledger is completion authority when a session has a task list; visible TODO state is its display projection. See [task and TODO contracts](task-todo-contract.md).

Building or checking does not authorize GitHub creation, push, or public release. Carry out those steps when the current user request authorizes them, and report the actual remote result separately from local work.

# Installation execution reference

**Audience: coding agents and contributors.** Use the named MCP tools and structured inputs below for authorized harness work. Users describe outcomes in the [usage guide](../usage/index.md).
<!-- date: 2026-09-09; synced_from: baseline f69cb6402683bb2e0bfe56ed04c63f808b263f06 plus current working-tree stdio MCP changes; scope: source, not live-host certification -->

[Usage](../usage/index.md) · [Contributing](index.md)


This guide covers installing and maintaining Neurath in a target project. Start with the [usage guide](../usage/index.md) for your first task. Package builds, agent integration steps, and typed verification are covered in [installation development](installation.md).

**English** · [한국어](../../ko/contributing/setup-reference.md)

This reference is for installation agents and contributors. The supported runtime is macOS/Linux,
Git, and Python `>=3.14,<3.15`. The target project can use any language. Quick setup provisions
the required Python automatically, so a separate manual Python installation is unnecessary.

## Quick setup

From the downloaded Neurath source directory, specify the project where you will actually
use the harness.

```sh
./setup /absolute/path/to/your-project
```

The installer handles the source build and wheel path. If uv is absent, it uses the
[official installer](https://docs.astral.sh/uv/reference/installer/), then installs Python 3.14
and Neurath into a persistent user tool environment. Each distribution's content gets a separate
environment; reinstalling the same content verifies and reuses the existing one. The global
`neurath` command is switched to the new environment only after project installation succeeds.
The target project's `.venv`, dependencies, and shell configuration files are left intact.
Install Git first if it is missing. Prepare a new directory with `git init /path/to/project`.
Use `./setup --self` to install into the Neurath development repository itself. This also uses
an independent tool environment, separate from the development `.venv`.

After the first installation, run this in another project:

```sh
neurath setup
# Or specify a target from any directory
neurath setup /absolute/path/to/another-project
```

If `neurath` is not on PATH, use the full executable path printed by the installer.
In an already installed project, you can also use `installation_plan` → `installation_apply`.

The first installation uses the `generic` profile and both hosts. Subsequent runs preserve the
selected hosts, profile, and user document and verification bindings. Specify the corresponding
options only when changing those selections.

```sh
./setup /path/to/project --host codex
./setup /path/to/project --host claude-code
neurath setup --dry-run
neurath setup --json
```

`--dry-run` shows changes by path without writing target files or printing original contents.
The source `./setup --dry-run` path prepares the tool environment; to avoid tool installation
as well, use an already installed `neurath setup --dry-run`.
Disable automatic uv downloads with `NEURATH_NO_BOOTSTRAP=1 ./setup /path/to/project`.

Installation output includes distribution integrity, file placement, hook protocol diagnostics,
and next steps. Actual host activation is separate. Check hooks in a new agent session in the
target project and configure the document and verification bindings below. The installer does
not automatically approve project trust or hook trust.

## Skill-name conflicts

If an existing project has skills with the same names, choose a prefix for the new installation.

```sh
./setup /path/to/project --skill-prefix neurath-
```

Neurath skills will then be invoked as `/neurath-debug`, `/neurath-review-code`, and so on.
Existing project skill names, content, and permissions are preserved; internal workflow contract
identifiers remain unchanged. Prefixes must start with a lowercase letter, contain only lowercase
letters, digits, and hyphens, and end with a hyphen. The option is available in `setup`, `plan`,
`install`, `update`, and `wizard`. Omitting it preserves the existing installation record.
Changing to another prefix requires uninstalling first. Conflicts at prefixed paths still stop
installation without overwriting existing files.

A prefix addresses skill-name conflicts only. If an existing harness manages its own session
state on the same host events or validates every skill directory against its own contracts,
first clarify runtime responsibilities and validation scope in the target project. The installer
does not automatically delete existing hooks.

User request examples are in the [installation guide](../usage/installation.md).

## Wizard interface reference

```sh
neurath --root /absolute/path/to/project wizard --output /private/path/neurath-plan.json
```

Choose a profile and hosts through the same `make_plan`/`apply_plan` engine. You may save only
the plan and exit. Without `--output`, plans go into `neurath-plans` in Git's administrative
directory and stay outside commits. Plans contain original settings for recovery and use file
mode `0600`. When specifying a path yourself, choose a new file in a private location.
Existing files and symbolic links are not overwritten.

## Bind the target repository

An edited `.neurath/project.json` remains user-owned. Updates and uninstallation do not
overwrite or delete the user's changes to this file.

```json
{
  "schema": 1,
  "documents": {
    "intent": "docs/product.md",
    "glossary": "docs/glossary.md",
    "decisions": "docs/decisions/"
  },
  "verification": {
    "check": {
      "argv": ["npm", "test", "--", "--run"],
      "cwd": ".",
      "success_codes": [0],
      "timeout_seconds": 300
    }
  },
  "protected_capabilities": {
    "connectors": [],
    "paths": ["docs/product.md"]
  }
}
```

Adapt the example command to the project. `argv` is not a shell string. Commands must fall within
verification already authorized for that project. Use `stdout_contains` for additional success
conditions. Even with a successful exit code, the verification record fails if repository files
change during execution.

```text
Named MCP tool verification_run (current input schema) {"check": "check"}
```

## Updates and recovery

Public release updates follow `releases_prepare` → exact user choice → `releases_apply`.
Prepare managed-file administration with `installation_plan`, then give `installation_apply` the returned plan_ref.
Actions include update/uninstall/restore; restore identifies an existing installation_id.
Use `installation_recover` for an interrupted journal. Replacing development source with a new distribution
uses the source bootstrap `./setup /target/Git-root`; subsequent agent operations use MCP.

For `AGENTS.md`, regular-file `CLAUDE.md`, and `.gitignore`, preserve user edits outside managed blocks
including their position and content. Edited managed blocks or files produce conflicts. Compare original and
current content through private installation records; do not force deletion or overwrite. Keep prior runtimes for recovery.

## Skill names and updates

Skills are invoked without a prefix, such as `/debug`, `/qa`, and `/review-code`. See the
[full skill catalog](../usage/skills.md) for names and purposes. Updating an existing installation
moves old Neurath-managed paths to their new locations and removes retired skills. If a user
skill has the same name or a managed file has been edited manually, installation stops and
preserves the content. Resolve the name or installation target before retrying; do not overwrite
the conflicting user skill.

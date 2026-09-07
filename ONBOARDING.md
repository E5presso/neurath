# Installing Neurath
<!-- date: 2026-09-07; synced_from: source and documentation at 3563609329437641570a5e45d87ceb99064e4c02; English and Korean editions updated together -->

**English** · [한국어](ONBOARDING.ko.md)

This guide is for both people and installation agents. The supported runtime is macOS/Linux,
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
In an already installed project, you can also use `.neurath/run setup`.

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

## Paste into your agent

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

Replace the source path with its actual location and send this request to Codex or Claude Code
in the target project:

> Read `/path/to/neurath/ONBOARDING.md` and install Neurath in this project.
> Preserve existing instructions, hooks, permissions, and dependencies, and use the default generic profile.
> After installation, bind the actual document paths and verification commands in `.neurath/project.json`.
> Ask me only for unknown information, then report local diagnostics and the hook trust steps I need to perform.

## Installation procedure for agents

1. Inspect the user-designated target repository's Git root and existing `AGENTS.md`, `CLAUDE.md`,
   `.agents/skills`, `.claude/settings.json`, `.codex/config.toml`, and `.codex/hooks.json`.
   Do not ask for the same installation approval again when it has already been granted.
2. Use the `generic` profile and both Codex and Claude Code by default. Product-specific profiles
   and framework policies are not included.
3. If a separate change preview is needed, inspect paths with the source
   `setup /target/Git-root --dry-run` or an installed `neurath setup /target/Git-root --dry-run`.
   Use the `plan`/`apply` route below only when an original-content comparison is needed.
   Plan JSON contains existing file contents: store it privately and keep it out of version control.
4. With downloaded source, run that source's `setup /target/Git-root`. If the tool is already
   available, use `neurath setup /target/Git-root` for installation and diagnostics. Do not use
   the target project's `.venv` or run `uv sync` in that project.
5. `setup` applies changes through the same `make_plan`/`apply_plan` engine. On a conflict,
   preserve the file and explain the cause. Do not resolve it by overwriting files, using
   `--force`, or bypassing permissions.
6. Bind the target repository's document slots and actual verification commands in
   `.neurath/project.json`. Do not invent missing documents. Ask only for information that is needed.
7. Review the diagnostics from `setup`. With a separate `apply` flow, run `doctor --protocol`.
   This does not prove host trust or live actor/evaluator identity.
8. In Codex, the user must trust the project and review the exact hooks through `/hooks`.
   In Claude Code, check project settings and hook loading through `/hooks`.
   The installer must not modify or bypass trust settings.

## Build a wheel and run individual steps

This advanced path is for building a wheel yourself or reviewing changes separately.
It need not be repeated after quick setup.

```sh
# Build only in the Neurath source repository
uv sync --locked
.venv/bin/python tools/build_manifest.py
.venv/bin/python -m build

# Use a new absolute path per distribution; do not reinstall or move existing environments
uv venv --python 3.14 /absolute/path/to/new-neurath-runtime
uv pip install --python /absolute/path/to/new-neurath-runtime/bin/python /absolute/path/to/neurath/dist/neurath-0.1.0-py3-none-any.whl

# For a new project, first run git init in the user-designated directory
/absolute/path/to/new-neurath-runtime/bin/neurath --root /absolute/path/to/project plan --output /private/path/neurath-plan.json
/absolute/path/to/new-neurath-runtime/bin/neurath --root /absolute/path/to/project apply /private/path/neurath-plan.json
/absolute/path/to/project/.neurath/run doctor --protocol
```

Place `--root` before the CLI subcommand. The launcher uses the Python path from the independent
tool environment, and hooks locate the launcher in the current Git worktree. If the tool environment
has moved, review an update plan. `neurath install` is the explicit installation command that
creates and applies a plan in one operation.

## Interactive wizard

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

```sh
.neurath/run verify check
.neurath/run engine scripts.agent_harness.state_cli --help
.neurath/run engine scripts.skill_harness.phase_runner --help
.neurath/run skill watch-pr monitor_runtime_readback.py --help
```

## Updates and recovery

After obtaining new source, rerun `./setup /path/to/project`. It prepares a separate tool
environment for the new distribution content, then applies and diagnoses the target installation.
Other projects retain their launchers and runtime environments. Update another project explicitly
with `neurath setup /path/to/other-project`. Keep previous environments so `restore` can
restore the earlier runtime too. If preparation is forcibly interrupted and leaves an incomplete
environment, the installer reports its path and stops. It does not automatically delete or
reinstall an environment that may be in use.

```sh
# Create an update plan using neurath from the new distribution environment
neurath --root /project plan --action update --output /private/update-plan.json
neurath --root /project apply /private/update-plan.json

# Restore only managed files to their original contents
neurath --root /project plan --action uninstall --output /private/remove-plan.json
neurath --root /project apply /private/remove-plan.json

# Undo the transaction using the ID returned by its application
neurath --root /project restore <installation-id>

# Recover a journal left by process interruption
neurath --root /project recover
```

For `AGENTS.md`, a regular-file `CLAUDE.md`, and `.gitignore`, user edits outside Neurath's
managed blocks retain their exact content and positions. If a managed block or another managed
file has been edited, update/uninstall stops with a conflict. Review before/after content in
`neurath-receipts/<id>.json` in the Git directory and reconcile the changes first.
There is no forced removal that discards original content. Empty directories and change history
may remain.

## Verification and repository conventions

`generic` is the only profile. Verification commands are not selected automatically merely
because a tool is present. For Python verification of exact test nodes, set
`verification.pytest.argv` to the executable in the project's test environment, such as
`["python", "-m", "pytest"]`. Do not include selectors (`-k`, `-m`), other test paths, or
configuration overrides in this binding. Use `verify <name>` for general verification and
the following command for typed phase verification:

```sh
.neurath/run engine scripts.agent_harness.verification_runner pytest --node tests/test_example.py::test_example
```

GitHub metadata requires no particular language or prefix by default. Projects that need these
conventions can set `metadata.language` to `"ko"`, or set `metadata.require_title_issue_prefix`
and `metadata.require_commit_subject_issue_prefix` to `true` as appropriate. Follow the target
project's instructions for branch and worktree paths. Cleanup requires an explicitly verified
`--base-branch` and `--remote-ref`.

The kit's fixed regression matrix runs through `tools/run_core_regressions.py` in Neurath's
development source. Target project verification cannot replace regression evidence for changes
to the kit itself.

## Skill names and updates

Skills are invoked without a prefix, such as `/debug`, `/qa`, and `/review-code`. See the
[full skill catalog](docs/skills.md) for names and purposes. Updating an existing installation
moves old Neurath-managed paths to their new locations and removes retired skills. If a user
skill has the same name or a managed file has been edited manually, installation stops and
preserves the content. Resolve the name or installation target before retrying; do not overwrite
the conflicting user skill.

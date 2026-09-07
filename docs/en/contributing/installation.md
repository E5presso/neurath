# Installation development and integration

**English** · [한국어](../../ko/contributing/installation.md)

<!-- date: 2026-09-07; synced_from: source and documentation at e1487a1718056b37b999d1343a1007b7e25f5c8c; English and Korean editions updated together -->

[Usage](../usage/index.md) · [Contributing](index.md)


Use this reference when changing or validating the installer, maintaining an agent integration, or testing the verification binding contract. For ordinary project installation, use the [user installation guide](../usage/installation.md). Run build commands only in the Neurath source checkout and installation commands against an explicit disposable or user-designated target.

## Agent execution reference

Contribute by describing the desired change, constraints, and acceptance conditions to your
coding agent. The agent performs the development commands and Neurath operations in this guide.
Command blocks document reproducible execution for agents and reviewers; they are not manual
setup requirements for users. Human host authentication and trust decisions remain with you.

[Setup](setup-reference.md) · [Collaboration](agents-reference.md) ·
[Memory](memory-reference.md) · [Skill compatibility](skills-reference.md)

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

## Inspect the internal command interfaces

These commands expose the existing integration interfaces; they are not required for a user
to start a normal task.

```sh
.neurath/run engine scripts.agent_harness.state_cli --help
.neurath/run engine scripts.skill_harness.phase_runner --help
.neurath/run skill watch-pr monitor_runtime_readback.py --help
```

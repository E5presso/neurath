# Developing Neurath
<!-- date: 2026-09-09; synced_from: baseline f69cb6402683bb2e0bfe56ed04c63f808b263f06 plus current working-tree stdio MCP changes; scope: source, not live-host certification -->

Harness deep dive: [system architecture](architecture.md) · [design principles and philosophy](design-principles.md) ·
[runtime lifecycle and recovery](runtime-lifecycle.md) · [capabilities and source map](capability-map.md).

[Usage](../usage/index.md) · [Contributing](index.md)


[English](index.md) · [한국어](../../ko/contributing/index.md)

Neurath is a Python 3.14 package with an isolated host runtime and kit-owned execution assets.
This guide is for changing Neurath itself: its documentation, installer, host adapters, skills,
or execution rules. To use the harness in another project, start with the
[usage guide](../usage/index.md). The agent runs the development commands below from the Neurath source checkout.

## Agent execution reference

Contribute by describing the desired change, constraints, and acceptance conditions to your
coding agent. The agent performs the development commands and Neurath operations in this guide.
Command blocks document reproducible execution for agents and reviewers; they are not manual
setup requirements for users. Human host authentication and trust decisions remain with you.

[Setup](setup-reference.md) · [Collaboration](agents-reference.md) ·
[Memory](memory-reference.md) · [Skill compatibility](skills-reference.md)

[Shared task tools and CLI compatibility](task-tools.md)

Implementation contracts: [Provider collaboration](collaboration-contract.md) ·
[Dynamic model planning and MCP operation](model-planning-mcp.md).
These record the target behavior and acceptance scenarios; they do not claim the migration is complete.

## Start with a bounded contribution

Describe the problem and the observable result you want to change. A useful bug report includes
reproduction steps, expected and actual behavior, the affected Neurath and host versions, and a
minimal example with private information removed. For a feature or a broad behavior change,
agree on scope and acceptance conditions before implementation. Documentation corrections should
identify the reader's task and the source that supports the corrected explanation.

Read `AGENTS.md` and the relevant source and tests. Keep unrelated cleanup out of the change.
When working with multiple agents, establish ownership and use separate worktrees for edits.

## Prepare the development environment

Use the committed lockfile to reproduce the development environment.

```sh
uv sync --locked
uv run --locked python tools/check.py
```

`tools/check.py` checks distribution integrity, Python diagnostics, installation tests, and
runtime contracts. Runtime tests use temporary Git repositories that are removed after execution.
Use `tools/run_core_regressions.py --target /private/path/to/fixture` to retain a fixture for debugging.

## Use the harness here

```sh
./setup --self
```

This installs a built copy into a persistent environment for that distribution, then applies it to this
repository. It does not run the harness from the development `.venv`. Review hooks in your host
and start a new session after installation. Project bindings are in `.neurath/project.json`.
Other installed projects retain their existing runtime. Previous environments remain available
for restoration; rerunning the same source verifies and reuses its environment.

The installed `.agents/skills/<name>`, `.neurath/rules`, and host hooks are generated files.
Change their source under `src/neurath/_assets`, then refresh the installation.

## Change, verify, refresh

Edit the source that owns the behavior. The [architecture](architecture.md) maps responsibilities;
[runtime assets](assets.md) explains the independent asset inventory. Generated files in an
installed project are not the source for a contribution.

```sh
# After editing runtime code or assets:
uv run --locked python tools/build_manifest.py
uv run --locked python tools/check.py
uv run --locked python -m build
./setup --self
Named MCP tool diagnostics_project (current input schema)
```

Define new installation behavior with a failing test first. Keep existing instructions, hooks,
permissions, dependencies, and edited bindings intact. Do not rewrite state JSON or forge host
identity to make a runtime test pass.

## Choose verification for the change

Start with the check that can detect the problem, then run the repository's full check before
delivery. State what each result proves; test counts alone do not establish host activation.

| Change | Focused verification | Additional evidence |
| --- | --- | --- |
| Documentation, locale paths, or navigation | `uv run --locked pytest -q tests/test_publication.py` | Both language editions, source-backed commands, resolved links, and actual source-distribution contents when packaging changes |
| Installer or setup behavior | A failing regression in the relevant `tests/test_*.py` before the fix | Existing-file preservation, conflict handling, and the affected update/recovery path in disposable targets |
| Runtime code, rules, skills, or contracts | Relevant package tests and kit-owned regressions | Regenerate the manifest, run the full check, build, and refresh self-installation |
| Host identity, hooks, or lifecycle | Relevant adapter and runtime regressions | Actual affected host flow, including trust and native identity, recorded separately from static/protocol checks |

The full repository check is:

```sh
uv run --locked python tools/check.py
```

To preserve a kit regression fixture for investigation, choose a private disposable path:

```sh
uv run --locked python tools/run_core_regressions.py --target /private/path/to/fixture
```

Keep raw evidence under ignored local storage such as `.validation/`. For installer integration
commands and exact-node verification bindings, see [installation development](installation.md).
[Host integration](hosts.md) and [validation scope](validation.md) distinguish local checks from
actual host evidence. Document any untested path instead of implying it passed.

## Prepare the change for review

Before submitting a contribution, check that both the behavior and its documentation agree.
Update English and Korean together, review the diff for unrelated files or local state, and
confirm generated runtime assets match their manifest when they changed.

Explain the following in the PR description:

- The concrete problem and the resulting behavior, with a before/after example when useful.
- The scope of the change and any compatibility or installation impact.
- Commands actually run, their results, and what each check covered.
- Remaining limitations or checks that could not be run.

Keep the contribution focused and use a commit message that describes its purpose. Repository
instructions determine any branch or issue conventions. Commit, push, PR creation, and package
publication are distinct actions; perform only the delivery steps authorized for the task.
Respond to review findings with source evidence and rerun checks affected by subsequent edits.

## Package boundaries

```text
src/neurath/
├── cli.py              # Public command line
├── doctor.py           # Integrity, placement, protocol checks
├── resources.py        # Immutable asset lookup
├── install/            # Projection, transactions, setup
├── hosts/              # Codex/Claude hooks, identity, lifecycle
├── runtime/            # Named tasks, state, verification, models, maintenance
├── providers/          # Model plans, policy inheritance, independent runs, recovery
├── agents/             # Messages, delivery, task reports, Newsroom, MCP
├── memory/             # Shared recall, reflection, observed recovery learning
├── _assets/            # Runtime engine, skills, rules, contracts
└── manifest.json       # Complete runtime integrity inventory

tests/
├── test_*.py           # Package, installation, adapter regressions
└── runtime/            # State, ownership, evaluation, phase contracts

tools/                  # Build and verification entry points
docs/en/usage/          # Install, use, operate, and troubleshoot
docs/en/contributing/   # Develop, verify, and review Neurath
docs/ko/                # The same relative paths in Korean
docs/assets/            # Shared images
```

## Verification evidence

Keep native host streams, installation plans, installation records, execution results,
verification records, review results, and debug fixtures in ignored local storage.
Public documentation contains the tested behavior and scope, not machine paths or
live identity tokens. Native activation requires the host's real trust and identity evidence;
`doctor --protocol` does not prove it by itself.

Publishing is a separate explicit step. Building a wheel or installing it locally does not
publish to GitHub or a package registry.

Generated skills, host settings, and the local launcher are ignored. Keep the project
binding and the public instruction files; `./setup --self` recreates the installation in
a fresh checkout. Installation preserves a byte-exact existing Neurath instruction block
and rejects conflicting edits. Review the actual hooks in each host before the first run.

## Maintain both documentation editions

Keep detailed documentation under `docs/en/` and `docs/ko/` with matching relative paths and filenames.
Use `usage/` for installation, everyday work, and operation; use `contributing/` for changing
and verifying Neurath itself. Root README and CONTRIBUTING entry points retain `.md` and `.ko.md` pairs.
Update both editions together, preserving the same behavior, commands, limits, and verification scope.
Each edition links to its counterpart for language switching; other links stay in the selected language.
Include both editions in source distributions. `tests/test_publication.py` checks these conventions.
Runtime instructions such as `AGENTS.md` and installed skill assets follow their own contracts.

[Architecture](architecture.md) · [Runtime assets](assets.md) · [Host integration](hosts.md) ·
[Installation design](installation-design.md) · [Validation](validation.md) · [Usage](../usage/index.md)

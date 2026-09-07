# Developing Neurath

[English](CONTRIBUTING.md) · [한국어](CONTRIBUTING.ko.md)

Neurath is a Python 3.14 package with an isolated host runtime and kit-owned execution assets.
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

```sh
# After editing runtime code or assets:
uv run --locked python tools/build_manifest.py
uv run --locked python tools/check.py
uv run --locked python -m build
./setup --self
.neurath/run doctor --protocol
```

Define new installation behavior with a failing test first. Keep existing instructions, hooks,
permissions, dependencies, and edited bindings intact. Do not rewrite state JSON or forge host
identity to make a runtime test pass.

## Package boundaries

```text
src/neurath/
├── cli.py              # Public command line
├── doctor.py           # Integrity, placement, protocol checks
├── resources.py        # Immutable asset lookup
├── install/            # Projection, transactions, setup
├── hosts/              # Codex/Claude hooks, identity, lifecycle
├── runtime/            # Engine entry points and verification commands
├── memory/             # Shared recall, reflection, observed recovery learning
├── _assets/            # Runtime engine, skills, rules, contracts
└── manifest.json       # Complete runtime integrity inventory

tests/
├── test_*.py           # Package, installation, adapter regressions
└── runtime/            # State, ownership, evaluation, phase contracts

tools/                  # Build and verification entry points
docs/                   # Architecture, host behavior, project bindings
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

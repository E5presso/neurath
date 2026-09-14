<!-- date: 2026-09-13; synced_from: 655c8768709e59b5e5012bab0adc4d888e3e7fa5 + current working-tree facts -->

# Contributing to Neurath

[한국어](CONTRIBUTING.ko.md)

Neurath development covers the installer, host integration, task runtime, collaboration, and the documentation that explains them. Begin with the [developer guide](docs/en/contributing/index.md) to find the component you want to change and the checks that establish its behavior.

If you want to use Neurath in another project, start with the [usage guide](docs/en/usage/index.md). That guide describes requests to your agent; the developer references here document the commands and contracts the agent works with.

## Prepare a change

Read [AGENTS.md](AGENTS.md) for repository instructions. Describe the concrete behavior you intend to change and identify its source and tests. For new installation behavior, add a test that fails before implementing the change. Preserve the target project's instructions, hooks, permissions, and dependencies.

Set up the development environment from this checkout:

```sh
uv sync --locked
```

Run the checks relevant to the component, then the repository check on the final change:

```sh
uv run --locked python tools/check.py
```

[Validation](docs/en/contributing/validation.md) explains what these checks cover and how to test distributions and actual host behavior. A source test, installation check, and live host observation answer different questions; include the results relevant to your change.

## Work in the source

Neurath owns the standalone runtime assets under [src/neurath/_assets](src/neurath/_assets). Installed skill and rule files are generated projections. Change the owned sources, regenerate the manifest when assets change, and follow the build and self-install sequence in [the asset guide](docs/en/contributing/assets.md).

Public documentation has matching English and Korean editions. Keep the same relative paths under `docs/en` and `docs/ko`, and update both editions for a behavior change. Root entry points use `.md` and `.ko.md` pairs. Usage pages describe natural-language requests and observable results; executable examples belong in developer references. Keep private installation plans, logs, original configuration, and verification artifacts outside public documentation and distributions.

## Make the change reviewable

Explain the problem, the resulting behavior, and any compatibility or installation impact. Include checks actually run and material gaps that remain. Link relevant source or tests so a reviewer can assess the result without reconstructing your working session.

Commit, push, pull request creation, and release publication follow the user's authorization for the task. For reporting a general Neurath defect or proposing a project-derived idea, see [reporting choices](docs/en/usage/reporting.md) and the [reporting contract](docs/en/contributing/reporting-reference.md).

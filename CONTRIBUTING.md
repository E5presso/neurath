# Contributing

[Home](README.md) · [한국어](CONTRIBUTING.ko.md)

The [core foundation](docs/en/core-foundation.md) and [task ledger](docs/en/task-ledger.md) describe current implementation and internal APIs. The [specification](docs/en/specification.md) defines product requirements. This candidate provides asynchronous SQLite access and the hook CLI; remaining business CLI commands and installation wiring are subsequent work.

## Environment and checks

Use Python 3.14.

```sh
uv sync --locked
uv run --locked python tools/install_quality_hook.py
uv run --locked pre-commit run --all-files
uv run --locked python tools/check.py
```

The Git hook installer uses a private hook directory and per-worktree settings for this checkout. It preserves shared/user configuration, chains an existing executable pre-commit first and does not overwrite unknown private hook directories.

Pre-commit and the required runner share `tools/quality.py`: Ruff lint/formatting, strict Pyrefly, Google-style pydoclint, docstring-language checks and structure/contract regression tests. The required runner then executes all behavioral tests and builds the wheel, emitting `NEURATH_CHECK_OK` on success. CI uses the same runner.

Type/docstring checks cover all production sources and development tools. Tests receive lint/formatting checks without requiring new docstrings or annotations. Existing docstrings, including tests and root Python configuration, use Korean summaries and natural-language field descriptions. Keep Google section headings and code/type identifiers; define argument types in signatures.

`tools/docstrings.py` is a minimal check for docstrings containing no Korean explanation outside code/formatting. It imposes no character quota, English/Korean ratio or per-line proportion. Review explanation accuracy and usefulness separately.

## Responsibilities and framework use

- Put invariants and transitions in domain objects owning the relevant state and meaning. Use cases coordinate reads, domain calls and persistence; they may raise, propagate or translate domain exceptions.
- Express ports through explicit `ABC`/`@abstractmethod` contracts and adapters through corresponding inheritance. Do not use Protocol.
- Use cases implement Spakky `IAsyncCommandUseCase`/`IAsyncQueryUseCase` and `run(command/query)`. Inputs inherit `AbstractCommand`/`AbstractQuery`; colocate dedicated inputs and result DTOs with their use case.
- Reuse Spakky domain bases, default repository CRUD/batches, declarative mapping/SchemaRegistry, constructor injection and request transactions. The core foundation describes current composition. Assess additional adapters/abstractions by responsibility and need.
- Express read-only list contracts with `Sequence`. Use `Self` for classmethod construction/conversion preserving the invoking subclass. Ruff UP checks supported Python 3.14 syntax.
- Use guard clauses and early returns for errors, inapplicable work and no-op paths so the normal flow stays shallow. Use continue/break in loops. Preserve validation, persistence, notification and transaction/finally cleanup order. Extract cohesive operations within the same responsibility.

Shared Ruff rules RET505/RET506/RET507/RET508 detect unnecessary else branches after return/raise/continue/break. Review other nesting for simplification without imposing an arbitrary depth limit or banning every if/else.

Structure checks inspect actual registered component ancestry and dependency direction. Concrete tests verify current repositories, input/output contracts, mapping, resource lifetimes, migrations and domain behavior. A function, exception, name or expression alone does not establish misplaced responsibility. Do not require a DTO/suffix/frozen result for every return or infer misplaced responsibility from Any/cast/Literal/ordinary suppression comments in custom AST checks. Standard Ruff ANN rules remain enabled, including ANN401. Syntax checks do not establish semantic design quality.

## Schema and preservation

Retain applied Alembic revisions and add a new revision for schema changes. Temporary-database tests verify existing data/foreign keys, rollback after migration failure, races/scope isolation and rejection of invalid stores. See [core foundation](docs/en/core-foundation.md#schema-and-preservation) for schema/initialization and [migration/recovery](docs/en/recovery.md) for the historical-user-data conversion boundary.

## Statement and branch coverage

`tools/check.py` measures the entire `src/neurath` directory, including dynamically loaded Alembic modules. Statements and branches must each reach 100%, with `missing_lines`, `missing_branches` and `excluded_lines` all exactly zero in the final report. Rounded percentages cannot pass.

Do not meet the threshold using omit settings, custom exclusions, `pragma: no cover` or `pragma: no branch`. JSON/XML reports are written to `coverage-out/` and retained as CI artifacts. Regression tests exercise real failure/healthy behavior and rejection of gate bypasses.

## Documentation

Keep public documents paired under `docs/en` and `docs/ko` with matching relative paths and equivalent scope. README and CONTRIBUTING also have English/Korean editions. Keep private paths and raw validation logs out of public documentation/packages. The [documentation index](docs/en/index.md) explains page responsibilities and separates implementation from product design.

## Service and repository naming

Production services end with `Service`; repositories end with `Repository`. Interfaces start with `I`, and concrete implementations replace that `I` with their actual technology. For example, `IDirectoryObserverService` is implemented by `GitDirectoryObserverService`, and `IProjectRepository` by `SQLAlchemyProjectRepository`.

`tools/architecture.py` scans all source modules and resolves ports, registration decorators, aliases and indirect inheritance. Missing suffixes, missing interface `I`, and missing or mismatched technology prefixes fail shared pre-commit and required CI. Current technology prefixes are `Git`, `Subprocess`, `Stderr`, `Posix` and `SQLAlchemy`. Add the corresponding prefix and positive/negative regression fixtures when introducing another technology; individual implementation classes are not allowlisted.

Use cases require only the `UseCase` suffix. Keep names such as `CreateTaskUseCase` without a technology prefix, and retain the existing Spakky `IAsyncCommandUseCase`/`IAsyncQueryUseCase` contracts instead of adding per-use-case interfaces for naming purposes. The same gate detects missing suffixes through decorators and direct or indirect inheritance.

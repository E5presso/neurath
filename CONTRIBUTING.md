# Contributing

[Home](README.md) · [한국어](CONTRIBUTING.ko.md)

Follow the approved specification and the responsibility boundaries in
[core-foundation](docs/en/core-foundation.md). Domain aggregates contain invariants.
Application ports use `ABC` and `@abstractmethod`; concrete use cases and repository
adapters explicitly inherit those ports. Each use case accepts a named immutable
command or query and exposes `execute`. ORM models use `DeclarativeBase`, `Mapped`,
`mapped_column`, and explicit domain conversion methods. Request adapters directly
use `Session.begin()`; do not add a custom transaction/unit-of-work framework.

## Required development checks

```sh
uv sync --locked
uv run --locked python tools/install_quality_hook.py
uv run --locked pre-commit run --all-files
uv run --locked python tools/check.py
```

The installer creates a private Git hook directory for this checkout and enables
Git's per-worktree configuration. It preserves shared/user hook settings, chains
an existing executable pre-commit hook first, and refuses to overwrite an unknown
private hook directory. Another worktree keeps its previous hook behavior.

The pre-commit configuration and required runner execute the same
`tools/quality.py`: Ruff lint/docstrings/annotations and formatting, strict mypy,
architectural AST checks, and negative/positive guard fixtures. CI executes the
required runner, followed within that runner by all behavioral tests and a wheel
build. The success marker is `NEURATH_CHECK_OK`. There is no current-source module
allowlist, old-source suppression baseline, `Any` escape hatch, or type/lint-ignore
policy. All future Python files under `src` are discovered. Tests are linted and
formatted but exempt from documentation/annotation style rules; production and
development tools have strict annotations and docstrings.

## Mechanically checked rules and review limits

The AST checker resolves import aliases and local inheritance to reject Protocol,
Literal, Any/cast escapes, custom named transaction/UoW APIs, Core/core modules,
forbidden layer imports, missing port ABC/abstractmethod declarations, non-nominal
repository/use-case/locator implementations, and non-declarative ORM mappings.
The ORM rule applies to runtime models; immutable Alembic revisions use SQLAlchemy
DDL constructs intentionally. Fixtures prove rejection, including import aliases,
indirect inheritance, DTO masquerading as a port, and newly added modules.

These checks establish concrete syntax and type relationships. They cannot prove
that a name describes a meaningful responsibility, a docstring is informative,
a generic class is not a disguised facade, or a renamed transaction abstraction
is semantically appropriate. Reviewers must inspect cohesion, invariants, transaction
scope, and whether additional abstractions are justified. Do not claim lint proves
those judgments. Deliberate dynamic code generation or reflective bypasses are not
an accepted substitute for explicit implementation.

## Preservation and implementation scope

All database tests use temporary paths. Preserve existing schema revisions and
add new Alembic revisions for schema changes. Test old schema fixtures, rollback,
concurrent requests, scope isolation, and byte preservation of rejected legacy
stores. No source test authorizes installation or conversion of user databases.

The previous 0.3.1 implementation and its implementation-specific tests were
removed from this candidate source tree instead of keeping an untyped parallel
runtime. Git retains that history. The new tests preserve #137/#154 behavioral
contracts and #140 task semantics; they do not claim the former full harness suite
still passes. Runner, host hooks, memory, migration, and public CLI/installation remain separate
implementation tickets. `setup` cannot install this incomplete candidate.

Keep public documentation paired under `docs/en` and `docs/ko`, with the same
relative paths and equivalent scope. Keep private paths and raw validation logs
out of public documentation and packages.

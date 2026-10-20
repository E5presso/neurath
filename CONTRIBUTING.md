# Contributing

[Home](README.md) · [한국어](CONTRIBUTING.ko.md)

Follow the approved specification and the responsibility boundaries in
[core-foundation](docs/en/core-foundation.md). Domain aggregates contain invariants.
Repository and observation ports use `ABC` and `@abstractmethod`; their adapters
explicitly inherit those ports. Use cases implement Spakky `ICommandUseCase` or `IQueryUseCase`. Inputs inherit `AbstractCommand` or `AbstractQuery` and are handled through `run()`. Define Command/Query, Result DTO, and UseCase in the same module, without imposing a name-based ban on other interfaces or shared data types. ORM models use Spakky declarative table bases, `Mapped`,
`mapped_column`, `relationship`, and explicit domain conversion methods. Request adapters directly
use the framework `Transaction`. Spakky Framework supplies `AbstractAggregateRoot`,
`IGenericRepository`, `AbstractGenericRepository`, `@Table`/`AbstractMappableTable`,
`SchemaRegistry`, `ConnectionManager`, `SessionManager`, and constructor injection.
Ports and adapters inherit basic CRUD and batch methods without redefining them.
Reuse existing request management rather than duplicating its behavior in wrappers; evaluate any additional adapter by its actual responsibility.

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
`tools/quality.py`: Ruff lint/docstrings/annotations and formatting, strict Pyrefly, Google-style pydoclint contract documentation,
architectural AST checks, and negative/positive guard fixtures. CI executes the
required runner, followed within that runner by all behavioral tests and a wheel
build. The success marker is `NEURATH_CHECK_OK`. There is no current-source module
allowlist or legacy exclusion baseline. Any, cast and ordinary suppression comments are not blanket semantic errors; assess actual tool results and meaning. All future Python files under `src` are discovered. Tests are linted and formatted but do not require new docstrings or annotations.
All existing code docstrings, including tests and root Python configuration, use Korean
summaries and natural-language field descriptions. Production and development tools
have strict annotations and Google-style docstrings. Pydoclint
checks Args, Returns, Yields, Raises, and Attributes sections against the signatures;
short summaries do not bypass checking. Signature annotations are the argument-type
source, so docstring argument descriptions do not duplicate those types.
`tools/docstrings.py` checks Korean prose in actual AST docstrings; Google section
headings and code/type identifiers stay in their standard syntax. It checks each
prose line for at least two Hangul characters and at least as many Hangul as English
letters after excluding identifiers and inline code. English prose with a token
Korean word is a negative fixture, not an accepted translation. Deliberate invalid
fixture strings remain test data; translation quality still requires human review.

## Mechanical checks and semantic review

The [complete harness-rule audit](docs/en/harness-rule-audit.md) records original intent and corrected scope for every prior diagnostic. AST checks cover confirmed contracts such as Protocol exclusion, dependency direction, and actual registered Spakky component bases. There is no blanket prohibition on Any/cast/Literal, names, context managers, or exception use.

Concrete tests cover current Sequence list contracts, inherited repository methods and CRUD, registered use-case inputs/framework contracts, current dedicated DTO colocation, actual mapping/resource lifetimes, and real Alembic upgrades. They do not prescribe a DTO, suffix, frozen result, or fixed component count for every operation.

Korean documentation remains required. Its minimal language check reports documentation with no Korean prose; it imposes no character quota, English/Korean ratio, or per-line language ratio. Correct language, meaning, ownership and the need for an abstraction require semantic review, not a claim that syntax proves them.

## Preservation and implementation scope

All database tests use temporary paths. Preserve existing schema revisions and
add new Alembic revisions for schema changes. Test old schema fixtures, rollback,
concurrent requests, scope isolation, and byte preservation of rejected legacy
stores. No source test authorizes installation or conversion of user databases.

The previous 0.3.1 implementation and its implementation-specific tests were
removed from this candidate source tree instead of keeping an untyped parallel
runtime. Git retains that history. The new tests preserve #137/#154 behavioral
contracts; they do not claim the former full harness suite still passes. Tasks,
runner, host hooks, memory, migration, and public CLI/installation remain separate
implementation tickets. `setup` cannot install this incomplete candidate.

Keep public documentation paired under `docs/en` and `docs/ko`, with the same
relative paths and equivalent scope. Keep private paths and raw validation logs
out of public documentation and packages.

Ruff UP checks Python 3.14 syntax. Classmethod factories returning their own type use `Self`.
The shared quality runner checks subclass construction, non-persistence of changes to returned objects outside a request, full state
preservation after rejected requests, Spakky request isolation and bootstrap failure cleanup.

Current default-method reuse is verified by inheritance and behavior tests. The
`core_0002` migration retains existing IDs, revisions and dependent records, using
epoch as an unknown-time marker for old metadata. Regression tests cover inherited
CRUD and schema/data/revision rollback after migration failure.

## Statement and branch coverage

The required `tools/check.py` measures the entire `src/neurath` directory with pytest-cov,
including Alembic files loaded under dynamic module names. Statements and branches must
both reach 100%. `--cov-fail-under=100` is followed by exact `missing_lines == 0` and
`missing_branches == 0` checks, so rounded percentages cannot pass. JSON/XML reports are
written to `coverage-out/` and uploaded as CI artifacts.

Do not meet the threshold using omit settings, custom exclusions, `pragma: no cover`,
or `pragma: no branch`. Keep regression tests rejecting configuration/comment bypasses
and actual statement-only or branch-only gaps. Behavioral tests cover data-preserving
downgrade, complete rollback of rejected destructive downgrade, invalid connections,
unrelated integrity failures and incomplete observation adapters.

Reports must also have `excluded_lines == 0`; a real report reaching 100% through exclusions is rejected.


Domain rules belong to the objects owning their state and meaning; request/query/storage orchestration belongs to use cases. Review responsibility through actual behavior and call flow. Use cases may raise, propagate, or translate domain exceptions. Functions, static methods, and raise statements are not forbidden by their shape. Dependency cycles, scope, correction preservation, and atomicity remain covered by domain/integration behavior tests. Syntax checks do not establish semantic ownership.

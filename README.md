# Neurath

[한국어](README.ko.md)

Neurath is being rewritten as a local, CLI-only agent harness. The approved
[specification](docs/en/specification.md) retains tasks, ordered execution phases,
hooks, memory, collaboration, and recovery. This checkout currently implements
the user-wide project/session foundation in #137 and task requirements, attempts
and TODO projection in #140.

The candidate package contains immutable domain aggregates, explicit application
ports and use cases, typed SQLAlchemy ORM repositories, and request-scoped session
functions. It does not provide the former MCP server, a public CLI, an installer,
or the rest of the planned harness. The previous runtime remains recoverable in
Git history. Existing installed distributions and user databases are not changed
by editing or validating this checkout.

This foundation is not an installable replacement for the running harness.
`setup` exits with an explanatory message; no obsolete console entry point is
published. CLI, migration, and installation work remains in the approved plan.

- [Task requirements, attempts and TODO](docs/en/task-ledger.md)
- [Foundation architecture, API, and boundaries](docs/en/core-foundation.md)
- [Development and enforced quality checks](CONTRIBUTING.md)
- [Full implementation plan](docs/en/implementation-plan.md)
- [Requirements and acceptance](docs/en/acceptance.md)
- [Documentation index](docs/en/index.md)

Source validation, wheel construction, public release, installation, and actual
host activation are separate results. No release or live activation is claimed
for this foundation.

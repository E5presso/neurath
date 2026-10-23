# Neurath

[한국어](README.ko.md)

Neurath is being rewritten as a local, CLI-only agent harness. The approved
[specification](docs/en/specification.md) retains tasks, ordered execution phases,
hooks, memory, collaboration, and recovery. This checkout currently implements
the #137 user-wide project/session foundation, #140 source/task/TODO ledger, #141 skill phase execution, the #142 [host runtime](docs/en/host-runtime.md), #143 [memory and handoff](docs/en/memory.md), #144 [collaboration and provider execution](docs/en/collaboration.md) libraries, and the #145 [project Newsroom](docs/en/newsroom.md) library and article CLI.

The candidate package contains mutable domain entities and immutable request values, explicit application
ports and use cases, inherited Spakky SQLAlchemy repositories and table mappings, and request-scoped session
functions. It provides spakky-typer hook, memory and handoff commands, but not the former MCP server, remaining business CLI commands, an installer,
or the rest of the planned harness. The previous runtime remains recoverable in
Git history. Existing installed distributions and user databases are not changed
by editing or validating this checkout.

This foundation is not an installable replacement for the running harness.
`setup` exits with an explanatory message; no obsolete console entry point is
published. CLI, migration, and installation work remains in the approved plan.

- [Foundation architecture, API, and boundaries](docs/en/core-foundation.md)
- [Development and enforced quality checks](CONTRIBUTING.md)
- [Full implementation plan](docs/en/implementation-plan.md)
- [Requirements and acceptance](docs/en/acceptance.md)
- [Documentation index](docs/en/index.md)

Source validation, wheel construction, public release, installation, and actual
host activation are separate results. No release or live activation is claimed
for this foundation.

- [Current internal source/task/TODO APIs](docs/en/task-ledger.md)

- [Skill procedure and phase execution APIs](docs/en/workflow-runner.md)

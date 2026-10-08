# Neurath

[한국어](README.ko.md)

Neurath keeps agent work accountable across requests, execution, delegation, and completion. It records task ownership and ordered phases, keeps evidence attributable, and separates a reported result from an accepted result.

This repository contains the fresh **Neurath 0.3.0** implementation. The MCP server name is `neurath`.

## Working with Neurath

Tell your connected agent what you want to accomplish and what would count as success. For example:

> Fix the reported problem. First explain the cause, then make the change, verify the result, and show the evidence before marking the work complete.

For a handoff:

> Ask another agent to inspect the change independently. Keep ownership of the original task here, and review its findings before accepting its result.

For resuming work:

> Show my unfinished tasks, their current phases, and the evidence already recorded. Continue the selected task without discarding its previous history.

These are workflow examples. An agent must use the operations actually available in its connected environment and identify unsupported actions. Task records do not execute an external agent, prove a native action happened, or supply human approval by themselves.

## Reading the result

A useful result identifies the current owner, task state, completed phases, remaining criteria, and applicable evidence. A delegate's report stays separate from the owner's acceptance. Completion requires the task's explicit requirements to be satisfied; a stopped process or a successful transport response is insufficient.

When checking an upgrade, distinguish the source checkout, installed distribution, reachable protocol, and integration actually loaded by the host. Each needs its own observation.

## Documentation

- [User workflows and capability boundaries](docs/en/workflows.md)
- [Requirements and acceptance specification](docs/en/specification.md)
- [Migration and recovery](docs/en/recovery.md)
- [Local candidate verification and native activation](docs/en/candidate-status.md)
- [Development and validation](CONTRIBUTING.md)
- [Documentation index](docs/en/index.md)

Existing data and unfinished work must be preserved during adoption. Read the recovery guidance before replacing a database or removing a worktree.

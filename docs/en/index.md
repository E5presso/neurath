# Neurath documentation

[Home](../../README.md) · [한국어](../ko/index.md)

This checkout is an internal Python library implementing the #137 project/session foundation, #140 source/task/TODO ledger, and #141 phase execution. The #142 hook CLI uses spakky-typer; #143 adds memory and handoff commands; remaining business CLI commands and installation wiring are subsequent work. The sections below distinguish product design from implemented behavior.

## Product design

| Document | Contents |
| --- | --- |
| [Requirements](specification.md) | Purpose, core and three surfaces, storage/project boundaries, capability requirements |
| [Execution architecture](architecture.md) | Runner, hook enforcement/completion, enclave restoration, collaboration and installation cutover |
| [Public skills/CLI](interfaces.md) | Triggers and input/output contracts for the planned 14 default skills and 19 business commands |
| [User workflows](workflows.md) | Planned experience from requests through evaluation, resumption and retrospective |
| [Migration/recovery](recovery.md) | Current support boundary and preservation requirements for subsequent migration/recovery |
| [Acceptance](acceptance.md) | 84 behavioral cases and implementation validation criteria |
| [Capability map](capability-continuity.md) | Omission checklist mapping historical purposes to replacement paths |
| [Implementation tickets](implementation-plan.md) | Execution order and ticket ownership of requirements/capabilities |

## Current implementation and development

| Document | Contents |
| --- | --- |
| [Project/session foundation](core-foundation.md) | Request lifetime, persistence/mapping, schema and internal API example |
| [Source/task/TODO ledger](task-ledger.md) | Internal APIs and preserved behavior for states, corrections, dependencies, attempts and waits |
| [Skill/phase runner](workflow-runner.md) | Selected definitions, attempts, process execution, reconciliation and task linkage |
| [Host runtime](host-runtime.md) | Native events, pause/resume, writer conflicts and liveness |
| [Current context, memory and handoff](memory.md) | Current facts, history, CLI, compaction restoration and work handoff |
| [Contributing](../../CONTRIBUTING.md) | Environment, coding guidance, quality checks and coverage |

Git history retains earlier runtime guidance and candidate-verification/audit records. These designs and temporary-database tests do not modify or activate an existing installation.

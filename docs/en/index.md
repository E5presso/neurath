# Neurath documentation

[Home](../../README.md) · [한국어](../ko/index.md)

The 2026-10-13 design was rewritten from the complete harness baseline, connecting task execution, independent outcome evaluation and user-selected retrospective. The installed 0.3.1 runtime does not implement the new design yet.

| Document | Contents |
| --- | --- |
| [Requirements](specification.md) | Purpose and complete components: TODO, phase runner, Stop, enclave, collaboration, Newsroom, providers, reflection, maintenance. |
| [Execution architecture](architecture.md) | Inputs/outcomes from request through actual work, phase advancement, collaboration, correction, resume, and finish. |
| [Public skills/CLI](interfaces.md) | Selected 14 skills/19 CLI commands and internal-only behavior. |
| [Capability map](capability-continuity.md) | Replacement public/internal/host paths and outcomes for historical 128 operations/33 skills. |
| [Acceptance](acceptance.md) | 84 behavior cases, real-host validation, implementation order. |
| [Implementation tickets](implementation-plan.md) | Tracking #153, 16 implementation tickets, dependencies and requirement ownership. |
| [Current contribution guide](../../CONTRIBUTING.md) | Current 0.3.1 development/command reference, distinct from the rewrite API. |
| [Earlier workflows](workflows.md) | Earlier 0.3.x implementation guidance, not a replacement for the new requirements. |
| [Existing recovery guidance](recovery.md) | Data preservation and existing installation recovery. |
| [Historical candidate verification](candidate-status.md) | Dated observations, not evidence of redesign completion. |

# Provider model selection

[한국어](../../ko/contributing/model-planning-mcp.md) · [Core contract](core-v2-spec.md)

The replacement core does not keep a separate model-plan progress ledger. Select a model only when the assignment needs an explicit override; otherwise retain the native default and inspect the observed setting. Obtain available choices from the actual host inventory. An unsupported model result is an execution failure, not evidence that the user goal is complete. Capability limitations do not require creating another app project.

Implementation references:

- [core/provider_commands.py](../../../src/neurath/core/provider_commands.py)
- [core/provider_job.py](../../../src/neurath/core/provider_job.py)

[Validation](validation.md) distinguishes source tests, installed protocol checks and actual host behavior.

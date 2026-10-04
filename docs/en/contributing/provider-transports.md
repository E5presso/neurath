# Provider execution

[한국어](../../ko/contributing/provider-transports.md) · [Core contract](core-v2-spec.md)

`provider_prepare` returns a command for native-host execution for an explicitly selected session or cross-provider assignment. It does not launch work in MCP or create an app project. Codex uses its app-server wire transport; Claude uses its Agent SDK. Preserve host settings, observe actual model and native completion, and retain disconnected results without blind retries. Interactive permission requests cannot be answered on behalf of a human. Native subagents use their host spawn/resume tools.

Implementation references:

- [core/provider_commands.py](../../../src/neurath/core/provider_commands.py)
- [core/provider_job.py](../../../src/neurath/core/provider_job.py)
- [providers/stdio.py](../../../src/neurath/providers/stdio.py)
- [providers/environment.py](../../../src/neurath/providers/environment.py)

[Validation](validation.md) distinguishes source tests, installed protocol checks and actual host behavior.

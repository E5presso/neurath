# Native host integration

[한국어](../../ko/contributing/hosts.md) · [Core contract](core-v2-spec.md)

Installed hooks invoke `neurath.core.hooks` and MCP invokes `neurath.core.mcp`, with explicit provider and common project root. A fresh `_call_id` correlates the exact native invocation with the MCP request; it does not carry permission. PreToolUse records the actual native actor and request, PostToolUse closes the binding. Reads remain available without a task or writer lease. Host trust, permission, sandbox and human interaction remain owned by the host.

Implementation references:

- [core/hooks.py](../../../src/neurath/core/hooks.py)
- [core/mcp.py](../../../src/neurath/core/mcp.py)
- [install/projection.py](../../../src/neurath/install/projection.py)

[Validation](validation.md) distinguishes source tests, installed protocol checks and actual host behavior.

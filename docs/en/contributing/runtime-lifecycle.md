# Native lifecycle and ownership

[한국어](../../ko/contributing/runtime-lifecycle.md) · [Core contract](core-v2-spec.md)

Native session and agent events identify actors. CWD identifies a resource, not a person or session. Before writes, claim the target checkout; readers and reports need no writer lease. A session interruption preserves unfinished Tasks. Normal Stop checks owned unfinished Tasks and outstanding assignment return obligations. SessionEnd closes invocation bindings without completing work.

Implementation references:

- [core/host_events.py](../../../src/neurath/core/host_events.py)
- [core/hook_adapter.py](../../../src/neurath/core/hook_adapter.py)
- [core/workspace.py](../../../src/neurath/core/workspace.py)

[Validation](validation.md) distinguishes source tests, installed protocol checks and actual host behavior.

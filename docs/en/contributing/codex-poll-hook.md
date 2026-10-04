# Codex event handling

[한국어](../../ko/contributing/codex-poll-hook.md) · [Core contract](core-v2-spec.md)

The replacement adapter consumes native prompt, tool, child and Stop events. It does not poll another progress ledger or maintain a provider-wave engine. Read state on a new event or concrete uncertainty. Waiting and progress reporting do not settle unfinished Tasks. Hook configuration, trust, delivered events and actual activation must be verified separately.

Implementation references:

- [core/hooks.py](../../../src/neurath/core/hooks.py)
- [core/hook_adapter.py](../../../src/neurath/core/hook_adapter.py)

[Validation](validation.md) distinguishes source tests, installed protocol checks and actual host behavior.

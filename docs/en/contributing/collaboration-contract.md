# Collaboration contract

[한국어](../../ko/contributing/collaboration-contract.md) · [Core contract](core-v2-spec.md)

Choose `subagent`, `session` or `cross-provider` according to scope, difficulty and the needed host. Worker, reviewer and executor are roles, not execution modes. A checkout does not imply a new session or project. Prepare a bounded assignment, observe its actual recipient, inspect the report and explicitly accept or reject it. A reported child result does not complete the parent Task. Reviewers must have independent context and cannot claim a writer lease.

Implementation references:

- [core/native_delegation.py](../../../src/neurath/core/native_delegation.py)
- [core/communication.py](../../../src/neurath/core/communication.py)
- [core/provider_commands.py](../../../src/neurath/core/provider_commands.py)

[Validation](validation.md) distinguishes source tests, installed protocol checks and actual host behavior.

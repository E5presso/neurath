# Task continuity

[한국어](../../ko/contributing/provider-continuity.md) · [Core contract](core-v2-spec.md)

Read retained Task and assignment state before continuing after an interruption. `task_adopt` preserves the Task ID and increments ownership generation after the former owner is observed stopped and the continuation instruction is quoted. It does not turn historical reports into new verification. A receiver claims needed writer resources separately. During the v1 transition the installer preserves original goals, dependencies and leases; unfinished work enters waiting state and skill context must be recovered.

Implementation references:

- [core/legacy_work.py](../../../src/neurath/core/legacy_work.py)
- [install/transition.py](../../../src/neurath/install/transition.py)
- [core/service.py](../../../src/neurath/core/service.py)

[Validation](validation.md) distinguishes source tests, installed protocol checks and actual host behavior.

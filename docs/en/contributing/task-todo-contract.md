# Task and TODO

[한국어](../../ko/contributing/task-todo-contract.md) · [Core contract](core-v2-spec.md)

Task is authoritative progress; TODO is its native display. States are open, running, waiting, completed and withdrawn. Waiting and failed attempts preserve obligations. Withdrawal requires an actual instruction source and is not success. Dependencies must be completed before work starts or completes. Native TODO updates do not advance phases or settle acceptance.

Implementation references:

- [core/domain.py](../../../src/neurath/core/domain.py)
- [core/service.py](../../../src/neurath/core/service.py)

[Validation](validation.md) distinguishes source tests, installed protocol checks and actual host behavior.

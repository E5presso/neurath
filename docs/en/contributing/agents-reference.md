# Agent execution reference

[한국어](../../ko/contributing/agents-reference.md) · [Core contract](core-v2-spec.md)

Read `session_status` and `task_list` on resume. Define a Task from retained input with observable acceptance; use its returned ID and revision to start it. Start the applicable skill, follow its current phase and display the native TODO projection. Use native tools for edits and checks. Complete each phase with its required evidence, then complete the Task against user acceptance. Failed attempts and elapsed time never complete the user goal.

Implementation references:

- [core/service.py](../../../src/neurath/core/service.py)
- [core/tool_schema.py](../../../src/neurath/core/tool_schema.py)

[Validation](validation.md) distinguishes source tests, installed protocol checks and actual host behavior.

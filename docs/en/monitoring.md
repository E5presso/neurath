# Requested external dependency monitoring

[Documentation](index.md) · [한국어](../ko/monitoring.md)

Monitoring belongs to a Task's actual external dependency, original condition, and follow-up scope. An ordinary wait does not start a watch. For a requested watch, the agent uses `task update --action wait --monitor output|pull_request` with the target, condition, scope, and observation. The CLI resolves the current execution and revision. Invalid targets roll back the wait transition as well.

## Returning to the same conversation

The response's `monitors[].callback` is `NEURATH_MONITOR_TICK <task-id> <number>`. It identifies an existing monitor, not an approval token. The agent schedules this callback at the requested interval through the **host's existing scheduler in the same conversation**. Neurath creates neither a model session nor a resident daemon. Preparing a callback does not prove scheduling or delivery.

The `UserPromptSubmit` hook handles the callback without storing it as a new user goal. It observes the currently owned task once. Initial or unchanged complete state returns `continue:false` before model work. A new event delivers the original condition, permitted follow-up, and actual observation through `additionalContext`. Submission is recorded after stdout returns, preventing repeated delivery of the same event on each callback. New observation errors and budget exhaustion receive one changed-state notice; repeated failures do not repeatedly wake a model.

- `pull_request`: reads the exact GitHub PR URL with `gh pr view`, comparing state, head, review, and checks while excluding timestamps and logs.
- `output`: reads the string `state` from the last complete JSON line in the final 64 KiB of an absolute file. Partial output is not a change.

A change proves neither dependency resolution nor task success. After inspecting the actual result, the executor uses `task update --action resume --monitor-event N --reason ...` to resolve the wait using that exact event. The normal waiting execution and peer resume through the same event flow. The host schedule must also stop after completion, cancellation, or budget exhaustion.

## State, preservation, and recovery

`context show` includes monitors and events owned by each task. `monitor status --task-id ... --monitor-number ...` reads details; `monitor tick` performs one diagnostic observation without a model call. Project/session/execution/generation overrides are available for explicit diagnostics; ordinary calls resolve them from the current host and stored monitor. A single tick's stderr output is not proof of native model delivery.

Observation reservations commit before external reads. External reads hold no DB transaction. Corrections, cancellation, handoff, and late outcomes are checked against the current ledger. Unknown resources are not declared stopped; handoff preserves events, remaining budgets, and cancellation. Closing a connection does not itself cancel a requested watch.

A37, A54, B23, and B24 cover changed/unchanged state, failures, cancellation, and preserved handoff. `tests/test_host_flow.py` exercises CLI→wait→callback→output receipt→resume in one SQLite store. Actual scheduler invocation and pre-model hook execution require separate host-specific installation tests. Unsupported scheduling is never reported as installed.

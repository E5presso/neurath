# Requested external dependency monitoring

[Documentation](index.md) · [한국어](../ko/monitoring.md)

The #146 candidate keeps monitoring, events, and notification history under an explicitly requested task dependency. Recording a wait does not start monitoring. `RegisterMonitorUseCase` requires the current task revision, owner execution, exact target, and finite observation budget. The target must equal the existing `ExternalWait.target`; an active monitor or unreconciled observation prevents duplicate registration. The original wait retains its condition and authorized follow-up scope.

## Observations and follow-up scope

The internal runtime performs one observation with `neurath monitor tick --project-id ... --session-id ... --task-id ... --monitor-number ... --execution-id ... --generation ...`. This command does not create a schedule or invoke a model or user hooks. Periodic dispatch belongs to the host runtime. Candidate installation and automatic schedule registration are outside this change.

- `pull_request` uses `gh pr view` for the exact `https://github.com/<owner>/<repo>/pull/<number>`, with existing GitHub CLI authentication. It normalizes PR state, head commit, review decision, merge status, and check states. Timestamps and execution logs do not trigger changes. The subprocess timeout is 30 seconds.
- `output` reads the last complete JSON line from the final 64KiB of the requested absolute file and uses only its string `state`. Examples: `{"state":"waiting"}\n` and `{"state":"done"}\n`. Incomplete fragments do not create events. Unsupported complete records and access failures remain visible as observation errors.

The first complete observation sets `initial_state` and `current_state` without creating a change event. Subsequent changes create numbered events containing evidence, the original condition, and the authorized scope. Identical states and output fragments cause no new events, notifications, or model invocations. A change is not automatically interpreted as satisfying the condition.

`GetMonitorUseCase`, `GetTaskUseCase`, and `neurath monitor status --project-id ... --session-id ... --task-id ... --monitor-number ...` expose current observations, exact events, ACK, resolution, notification failures, required actions, remaining budgets, and unknown resources. Reads do not observe again, resend, or resume. `AcknowledgeMonitorEventUseCase` records consumption of one event. `ResolveMonitorEventUseCase` checks the current requirement, dependency, and owner execution, records explicit resolution evidence, and resumes the same attempt as active. ACK and dependency resolution are separate from task success.

## Cancellation, recovery, and handoff

Observation reservations and budget consumption commit before external reads. Neither observation nor notification holds a SQLite write transaction. A pending reservation prevents another tick from duplicating that observation. Latest task state is checked after external work; cancellation and corrections prevent late results from creating new events. Task resolution, current result reporting, corrections, invalidation, explicit execution cancellation, and actual Interrupt events stop new observations and submissions.

`RecoverMonitorUseCase` requires the exact reservation ID, current owner execution and generation, and an actual termination observation. RUNNING and UNKNOWN cannot release resources. This is an internal observation-result contract, not a public CLI for declaring termination. Recovery preserves cancellation and remaining budgets. Actual host resource observations must come from the host adapter; the candidate single-observation CLI does not itself track native scheduler resources.

Session handoff retains the existing actual execution termination and writer-release requirements. In-flight observations or notification submissions with unknown results additionally block handoff. Once reconciled, only the monitoring owner and generation change. Cancellation, initial observation, pending events, delivery attempts, and remaining budgets survive. Reconnecting the source session creates no new monitor or execution.

## Notifications and validation boundaries

Notifications preserve `written → submitting → submitted/failed`; only an actual confirmation for that submission can become `delivered`. The default adapter reports `submitted` after complete stderr output and flush return. This does not confirm native notification receipt, user read, or delivery into model context. Failures retain their cause and required action and allow at most three submissions per event. A lost result remains `submitting` and is never automatically resubmitted. Notification failure, reconnection, and unchanged waits never invoke an executor.

`tests/test_monitoring.py` checks A37, A54, B23, and B24 through real scanning, SQLite, CLI, and deterministic external fixtures. `core_0011` preserves existing tasks, source text, and waits and rejects downgrade when monitoring history exists. Source validation is distinct from installation, periodic scheduling, native notifications, and actual model delivery.

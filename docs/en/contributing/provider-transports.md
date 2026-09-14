<!-- date: 2026-09-14; synced_from: 655c8768709e59b5e5012bab0adc4d888e3e7fa5 + current working-tree facts -->

[한국어](../../ko/contributing/provider-transports.md)

# Own the connection that runs independent work

An independent provider run needs a durable execution identity and an owned native connection. The logical provider instance survives individual process generations; its recipient address is distinct from a PID, socket, or native session UUID. The issuer remains responsible for follow-up while work or unacknowledged obligations remain, including after the issuer's model turn ends.

## Available execution foundations

| Provider surface | Owned implementation | Boundary |
| --- | --- | --- |
| Codex | Official app-server worker with JSON-RPC create/read/start/steer/interrupt and recorded-session restoration | Does not attach to or resume another live client's session |
| Claude Code | Official Claude Agent SDK asynchronous client, streamed responses, serial queries, interrupt, and recorded-session restoration | Query, response consumption, and interrupt stay on the same client |
| Native/app peer tool | Discovered supported route | Must actually execute the returned route; discovery is not delivery |
| Claude Desktop/Cowork | No external lifecycle adapter | Reading history does not establish an owned delivery bridge |
| Saved bounded CLI runner | Legacy short read-only status/cancel/continuation compatibility | Not the normal independent-session transport or an MCP migration substitute |

The collaboration contract covers Codex→Codex, Codex→Claude, Claude→Codex, and Claude→Claude. The same provider brand does not imply the same owned instance. Validate the actual adapter and native behavior for each direction; these contract requirements do not certify a fresh host merely because the source supports a route.

A provider session does not require the user to watch it, remote visibility, or membership in a saved desktop project. The current schema accepts optional `project_id` for supported routes; this is not a claim that automatic app-project association is complete. Do not write the app database or fabricate membership. When a supported adapter receives an explicit project ID, compare the actual returned identity to that exact request.

## Observe policy from the immediate creator

The inherited source is the immediate creator's currently admitted native policy. A restricted intermediary cannot restore the broader root's rights. Observe approval behavior, tool restrictions, filesystem and network scope, and provider-specific fields separately, with their sources. Configuration files are candidates for settings; they do not prove effective loaded settings or in-memory overrides.

Same-provider execution must preserve the observed relevant restrictions. Cross-provider execution needs a semantic mapping, not similar mode names. Map workspace-relative scope to the child's target and required shared state, without granting another owner's source tree. Known explicit denies and hooks remain relevant even under a broad permission mode.

| Dimension | Codex | Claude Code |
| --- | --- | --- |
| Filesystem/execution request | `mode`: `read-only`, `workspace-write`, `danger-full-access`, or default `inherit` | Default `inherit`; explicit `native` requires `permission_mode` and observed provider policy |
| Approval behavior | `approval_policy`: `never`, `on-request`, `untrusted` | `permission_mode`: `plan`, `dontAsk`, `default`, `acceptEdits`, `auto`, `bypassPermissions` |
| Approval reviewer | `approvals_reviewer`: `user`, `auto_review` | Do not inject Codex-only fields |
| Planning behavior | `collaboration_mode`: `default`, `plan` | Native `plan` semantics remain distinct from OS confinement |

The current broad cross-provider mapping candidate is Codex `danger-full-access` plus `approval_policy=never` outside Plan mode, or Claude `bypassPermissions`, only when known restrictions remain preserved. Other dimensions may be explicitly unsupported. `dontAsk` must not become `bypassPermissions`. A disabled SDK sandbox does not prove unrestricted ambient OS access; retain unknown OS conditions as unobserved.

Unsupported or unverifiable dimensions block substantive assignment and identify the missing observation. Silently widening or narrowing a policy and calling it successful inheritance is incorrect. This is a bounded mapping contract, not complete copying of every native provider setting.

## Use the receiving provider's native settings

For explicitly authorized `target-native` execution, the plan uses `execution.mode="target-native"` and the run uses `mode="target-native"` with the same assignment and exact plan revision. The target's existing defaults, hooks, and tool rules are retained. Source settings and credentials are not copied, and this mode is not a fallback after failed inheritance.

Codex defaults are observed through native `config/read`, including supported workspace sandbox dimensions. Claude resolves its existing user, project, and local settings. Unsupported or unobserved defaults reject preparation. Conflicting explicit approval, reviewer, collaboration, or permission settings are rejected instead of overriding the target. After creation, actual model, policy, activation, and ownership still need observation. [Target-native tests](../../../tests/test_target_native_policy.py) cover the supported policy checks.

## Admission, preparation, and execution

Use `provider_capabilities` with a provider name to inspect capabilities. `provider_route` takes `provider` and an operation (`create`, `discover`, `connect`, `status`, `message`, `resume`, `cancel`, or `peer`) to prepare a supported route. Its proposal alone proves neither execution nor ownership.

For a new task that must belong to a Codex app project, inspect the existing app creation route with the project ID returned by `list_projects`. Follow the host tool's explicit new-task and model-selection conditions, and verify actual native settings after creation. An app project ID and a native app-server project ID are different identifiers; a successful native metadata update does not establish app membership. The new Codex session's `session_status.app_project` reads its local app affiliation record without changing it. `assigned` requires an existing local project; missing, inconsistent, or unsupported records remain `unobserved`. This diagnostic neither changes execution readiness nor proves that a remote UI is displaying the task.

For authorized independent creation, prepare an observed model plan as described in [model planning](model-planning-mcp.md). `provider_run` requires `worktree` and `assignment` structurally; the execution contract also binds the exact prepared `plan_id`, `plan_revision`, assignment revision, effective policy, and stable key before durable admission. A returned run ID with `accepted` reports admission, not completed preparation or implementation.

Before sending substantive work, the owned connection checks installed distribution and placement, actual native activation, effective policy, actual model, and the target's own worktree claim. A new worktree does not automatically contain ignored installation files. Readiness is specific to the observed session and prompt generation; it does not confer independent reviewer authority.

Claude consumes both the SDK Result and the response iterator before a separate assignment query. The same owned control path revalidates identity, prompt generation, policy, install, and claim. A prepared session with a closed turn is quiescent and owned; it must not be reported as actively executing an assignment.

| Observation | What the issuer can conclude |
| --- | --- |
| Durable run acceptance | A recorded run exists and can be diagnosed by ID |
| Native session created | A real provider identity exists; readiness can still fail |
| Preparation complete | The observed conditions permit the bound assignment |
| Waiting for approval/input | Work requires the corresponding authorized readiness event |
| Native completion report | A turn produced a result; requested task effects still need inspection |
| Cancel request accepted | Cancellation was requested; observe the resulting state before claiming exit |

For a Claude result, an explicit interruption takes precedence and is classified as cancellation. Otherwise, deferred tool use indicates an approval wait, even when historical permission denials are present. Without a pending deferred tool, an error or historical permission denial is classified as failure. Completion metadata records `permission_denial_count` and `approval_pending`; these fields grant no permission and do not establish task success.

## Keep long work responsive

The detached worker emits creator-linked lifecycle events and messages for start, waits, errors, disconnect, cancellation, and completion. Ordinary tasks have no lifetime timeout; individual connection, write, and response operations retain deadlines. While a native result is pending, the event loop must still handle messages and cancellation.

The issuer-owned connection remains while issued work or unACKed obligations remain. An idle Codex session receives a new turn; an active Codex session receives a steer for the actual current turn. Claude queues durable notifications until the current Result and response iterator are consumed. Mid-stream input is not acknowledged as an independently completed turn.

No receiver-only model session, heartbeat, or periodic completion scan is needed. Use `provider_status` after a relevant event or error for diagnosis, not as a completion-polling loop. Closing a connection preserves late notifications and permits an input write already started to finish. Full-body reading, ACK, and retry semantics remain those of [the delivery contract](collaboration-contract.md).

## Restore a recorded execution

An issuer process ending does not cancel authorized work in another instance. Recovering messages is distinct from recovering an interrupted computation; a powered-off host or lost storage cannot promise continued execution.

`provider_recover` takes `run_id` and `key` for the current issuer's recorded execution. Before restoring, it verifies the prior worker generation and native identity, and requires the previous process and connection to be closed. An OS worker lease rejects concurrent recovery and cancelled work. A `recovery-accepted` result is only admission.

The recovered owned connection restores the same recorded native session, rechecks policy and readiness, and reconnects pending delivery. It does not repeat the original assignment. If prior closure cannot be established or the session cannot be restored, retain the blocker and diagnostic identity. Do not create a replacement session under the same identity or blindly rerun uncertain creation. For quota exhaustion that requires another provider to take over, use the separate [memory pull and adoption flow](provider-continuity.md). It imports available source context and unfinished tasks rather than restoring the same provider execution.

## Evidence by layer

[Provider jobs](../../../src/neurath/providers/jobs.py), [recovery](../../../src/neurath/providers/job_recovery.py), [supervision](../../../src/neurath/providers/supervision.py), [permission inheritance](../../../src/neurath/providers/permission_inheritance.py), and [runtime execution](../../../src/neurath/runtime/provider_execution.py) implement admission and owned execution. [Provider policy](../../../src/neurath/runtime/provider_policy.py) defines supported checks.

[Provider-job tests](../../../tests/test_provider_jobs.py) and [inherited-mode tests](../../../tests/test_inherited_provider_modes.py) cover deterministic fixtures. Native acceptance additionally observes all four directions, restricted intermediaries, missing install/claim, effective model and policy, idle issuer delivery, death before and after ACK, stale generations, recovery, and long work accepting cancellation. Keep those native observations separate from source tests and installation checks in [validation](validation.md).

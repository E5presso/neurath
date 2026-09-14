<!-- updated: 2026-09-14; synced_from: 243400e58ca74c7fd79bcdd86b488953fa743b97 -->

# The agent that owns the work

[한국어](../../ko/contributing/agents-reference.md) · [Contributor start](index.md)

Neurath connects a coding agent's current user request to durable work records, host observations, and the right to change a checkout. This reference explains those roles before introducing their tools. For a first encounter with the product, begin with [the user walkthrough](../usage/start-here.md).

Suppose a saved filter in the user's hypothetical web application disappears after refresh. This is a target-application example, not a Neurath feature. The user wants the cause fixed, the selection to survive refresh, and the existing interface preserved. The agent may investigate the save API, inspect reload behavior, or ask another agent to reproduce the failure. These are ways to fulfill the same request. Finishing an investigation, reaching a token limit, or writing a handoff does not change what the user asked for.

## Distinguish work, conversation, and checkout

| Term | Meaning in this example |
| --- | --- |
| Task | The requested outcome and observable acceptance conditions, retained in the task ledger. |
| Session | One native Codex or Claude Code interaction, identified and observed by that host. |
| Root | The primary actor in a native session; the owner of its task decisions. |
| Native child | A direct subordinate actor whose parent relationship the host attests. It can investigate a bounded part of the filter defect. |
| Peer | Another independent session participating in the same local Git project. Discovering it does not make it a child. |
| Provider run | Neurath-supervised execution in an independent native root, with separately checked settings and ownership. |
| Worktree | A particular Git checkout. Linked worktrees can share project records while remaining distinct write targets. |
| Claim | A current write lease for that worktree. Its epoch and fencing token reject stale owners. |
| Receipt | A record of a particular observed event. Its meaning is limited to that event. |

The task ledger owns completion state; a host TODO list is a view of that ledger. The host owns native identity and effective permissions. Neurath's current binding connects a tool call to that identity. Names, paths, copied session IDs, and remembered claims cannot replace a valid binding.

## Establish the current operating state

`session_status` reports installation, native activation, effective mode, and worktree ownership. `detail="summary"` is the default; `detail="full"` adds the capability catalog. Read the dimensions separately: installed files do not prove an active hook, and an active session does not prove that this root owns the checkout.

`session_inspect`, `turn_inspect`, and `worktree_inspect` provide narrower observations. Use `worktree_claim` when the authorized work needs the current root's claim; it does not provide a force-takeover path. Save returned lease data together in private working state. A release needs the returned `expected_lease_epoch` and `fencing_token`; a stale or foreign token must fail. Never publish that token or invent a replacement.

The active host supplies `_neurath_binding` to named MCP calls. The agent must not construct it from diagnostics. Missing native registration, a missing user-prompt receipt, or a foreign live claim is a prerequisite failure to resolve at its actual source.

### What app project membership tells you

For a verified active Codex root, the status report can include `app_project`. This is a bounded, read-only observation of app-owned local assignment records. `assigned` identifies a matching local project record, `unassigned` means the app explicitly recorded a projectless task, and `unobserved` means the evidence is absent, inconsistent, unsupported, or too large to inspect. The reader caps the app state file at 16 MiB and returns only the relevant assignment fields.

This field is diagnostic. It does not grant task authority, alter readiness, inspect a remote app, or prove what a window currently displays. A `project_id` in native execution metadata is a separate fact. When the user requests an app-created root, use the app's `create_thread` capability together with its project/plugin context and assess the app result. `provider_run` creates supervised provider work; it is not a substitute proof of app membership.

## Turn the request into accountable work

The root first reads `task_list`. `task_define` records a bounded goal, its prompt/ticket/spec sources, acceptance conditions, and dependencies using the returned ledger revision. `task_start` chooses a task using both the ledger and task revisions. `task_resolve` records `succeeded`, `failed`, or `invalidated`, with evidence references and a summary under the same revision checks.

The ledger distinguishes `pending`, `in_progress`, `succeeded`, `failed`, and `invalidated`. Terminal history is immutable. `all_terminal` is separate from `all_succeeded` and `unsuccessful_task_ids`: a terminal failure is not successful delivery. Initial definition needs the actual native user instruction receipt or a retained validated same-session prompt source. After a later prompt arrives, choose explicitly whether a new definition continues the original requirement or implements the new request; a status question must not silently become a new goal. A peer-resumed turn can use retained validated prompt sources without fabricating a fresh user receipt.

Starting and successful resolution require terminal dependencies; failed or invalidated outcomes can be recorded before dependency settlement. Resolution is an owner report with `assurance="agent-report"`, not independent certification. The final ledger check and root closure share one SQLite transaction so a concurrent task append cannot disappear. A stale or failed TODO display cannot rewrite that truth.

For the filter defect, acceptance should include reproduction, a confirmed cause, retained selection after a fresh reload, and interface preservation. “The save API returned success” establishes one observation. It cannot stand in for the reload test. A failed attempt also leaves the original user requirement in force; necessary follow-up work must remain represented.

Native goal reminders help the agent keep that distinction visible. They run on eligible prompt/tool events at the first event, a changed prompt, 12 distinct completed tool events, or the next eligible event after 300 seconds. Task definition, start, and resolution also receive decision context immediately before the tool call. Reminders are bounded to 2,400 bytes and at most four task excerpts. They provide context for judgment without changing task state or deciding semantic success.

## Returning to the user is a work decision

An ordinary Stop is checked against the active work. Asking a question, reaching a budget limit, finishing a verification step, or preparing a checkpoint does not itself permit the agent to bypass an unfinished user goal. A limit can require a different method or an authorized continuation. A checkpoint records what is known and what remains; see [memory and learning](memory-reference.md).

Normal host `SessionEnd` preserves resumable sessions, tasks, bounded session facts (the enclave), and claims. The kernel's `SessionEnded` is permanent. A verified resume can retire an interrupted older foreground while preserving unfinished work; a fork is a new root with a separate claim requirement. Explicit user interruption remains a native host operation. A Stop block requests another model turn and is not a security boundary; stale Stop ingress has a read-only diagnostic route and cannot close a newer verified turn.

The root can ask a native child to inspect API storage and responses while it investigates reload behavior, or contact a discovered peer for an existing finding. Keep the child's bounded assignment and parent relationship explicit. `delegation_prepare` records preparation; it does not spawn the child. The actual native host action and its observed child identity complete that part of the setup. [The collaboration contract](collaboration-contract.md) explains messages and delegated results; [provider execution](provider-transports.md) explains independent roots.

## Source and focused evidence

The identity and task rules are implemented in [src/neurath/hosts/identity.py](../../../src/neurath/hosts/identity.py), [src/neurath/_assets/scripts/agent_harness/task_service.py](../../../src/neurath/_assets/scripts/agent_harness/task_service.py), `task_ledger.py`, and `worktree_registry.py`. Diagnostic app membership is in [src/neurath/hosts/app_projects.py](../../../src/neurath/hosts/app_projects.py); reminders are in [src/neurath/runtime/goal_reminders.py](../../../src/neurath/runtime/goal_reminders.py).

Relevant regression coverage includes [tests/test_app_project_observation.py](../../../tests/test_app_project_observation.py), [tests/test_goal_reminders.py](../../../tests/test_goal_reminders.py), and [tests/runtime/agent_harness/test_foreground_stop_aggregate.py](../../../tests/runtime/agent_harness/test_foreground_stop_aggregate.py). These references identify source-level checks. They do not certify a particular installation, current MCP connection, or visible native app session.

Current discovery exposes 128 public named tools over 138 internal operations. Tool presence still needs a live native binding. An `UNATTESTED` session, turn, or child cannot mutate execution state. Codex child verification uses the actual spawn result and child transcript parent/session metadata; Claude uses one-time parent Agent-call evidence in the child transcript. Late registration can retry identity verification at the first state operation, but shell and writes remain `child-identity-unverified` until real lineage is established.

## Named input reference

The tables below are the current named-tool input contract. Nested required fields are required when their parent object or array item is supplied. Schema acceptance is only the first check; native identity, ownership, source, revision, and operation-specific prerequisites still apply. The host supplies `_neurath_binding`; do not synthesize it.

Every response has `ok` and `operation`. A successful call carries its canonical `result`; a failure carries `error.code`, `error.message`, `error.state`, `error.retryable`, and `error.next_action`. An `ok` envelope establishes the stated operation only, not the user goal. Preserve returned IDs and revisions for dependent calls.

### `session_status`

| Field | Presence / default | Type and limits |
| --- | --- | --- |
| `detail` | optional; default `"summary"` | text: `"summary"`, `"full"` |

### `session_inspect`

No agent-supplied input fields.

### `turn_inspect`

No agent-supplied input fields.

### `worktree_inspect`

No agent-supplied input fields.

### `worktree_claim`

No agent-supplied input fields.

### `worktree_release`

| Field | Presence / default | Type and limits |
| --- | --- | --- |
| `expected_lease_epoch` | required | integer; 1–9007199254740991 |
| `fencing_token` | required | text; 1–256 characters |

### `task_list`

No agent-supplied input fields.

### `task_define`

| Field | Presence / default | Type and limits |
| --- | --- | --- |
| `tasks` | required | array; 1–64 items |
| `tasks[].key` | required | text; 1–512 characters |
| `tasks[].title` | required | text; 1–512 characters |
| `tasks[].goal` | required | text; 1–16000 characters |
| `tasks[].sources` | required | array; 0–31 items |
| `tasks[].sources[].kind` | required | text: `"prompt"`, `"ticket"`, `"spec"` |
| `tasks[].sources[].reference` | required | text; 1–4096 characters |
| `tasks[].sources[].revision` | required | text; 1–4096 characters |
| `tasks[].acceptance` | required | array; 1–32 items; text; 1–16000 characters |
| `tasks[].dependencies` | required | array; 0–64 items; text; 1–128 characters |
| `expected_revision` | required | integer; 0–9007199254740991 |
| `key` | required | text; 1–512 characters |

### `task_start`

| Field | Presence / default | Type and limits |
| --- | --- | --- |
| `task_id` | required | text; 1–128 characters |
| `expected_revision` | required | integer; 0–9007199254740991 |
| `expected_task_revision` | required | integer; 0–9007199254740991 |
| `key` | required | text; 1–512 characters |

### `task_resolve`

| Field | Presence / default | Type and limits |
| --- | --- | --- |
| `task_id` | required | text; 1–128 characters |
| `expected_revision` | required | integer; 0–9007199254740991 |
| `expected_task_revision` | required | integer; 0–9007199254740991 |
| `key` | required | text; 1–512 characters |
| `status` | required | text: `"succeeded"`, `"failed"`, `"invalidated"` |
| `references` | required | array; 1–32 items; text; 1–4096 characters |
| `summary` | required | text; 1–4096 characters |

### `delegation_prepare`

| Field | Presence / default | Type and limits |
| --- | --- | --- |
| `delegation_id` | required | text; 1–128 characters |
| `assignment` | required | text; 1–8192 characters |
| `task_id` | optional; default `null` | text; 1–128 characters / null |
| `expected_task_revision` | optional; default `null` | integer; 1–9007199254740991 / null |
| `key` | required | text; 1–512 characters |

<!-- last_updated: 2026-09-14; synced_from: 243400e58ca74c7fd79bcdd86b488953fa743b97 -->
# Calling Neurath's named tools

[한국어](../../ko/contributing/task-tools.md)

Use native editing and command tools to change and check project code. Use Neurath's named MCP tools to record the task, coordinate authorized participants, retain evidence, and manage runtime state. This division keeps ordinary coding work direct while giving continuation a durable record.

A **task** records a bounded user goal and observable **acceptance conditions**. The native session's **root actor** owns its task list. A **worktree claim** identifies the owner of coordinated work in the checkout. A **receipt** records a particular event or report. A workflow's **phases** organize a procedure; a **review** assesses defined work. Read [architecture](architecture.md) if these roles are new.

## Discover the current contract

The MCP server publishes named tools through `tools/list`. The current source exposes 128 public tools from 138 internal operations. Use the discovered input schema for the installed version. The [capability map](capability-map.md) groups every public name by purpose.

Each operation accepts a closed JSON object: unknown fields are rejected. A native hook supplies `_neurath_binding` for the current invocation; the agent must not supply invented actor, session, turn, or binding values. `harness_bypass` is the explicit exception: it can read or restore the bypass switch without a native binding, including while the other named operations are unavailable during bypass.

For `harness_bypass`, omitting `enabled` or passing `null` reads the current worktree switch; `true` enables bypass and `false` restores Neurath hook constraints. The configured MCP connection handles this emergency read/change without a native binding or an available call-worker slot, including when kernel storage cannot supply normal admission. The switch leaves host permissions and existing history intact and grants no authority for another task or tool. Other named calls still need their own valid native admission after constraints are restored.

For source-level schema inspection, contributors can inspect `src/neurath/runtime/task_schema.py`, its imported definition modules, and `definitions()` / `arguments()`. Current discovery uses `phase_*`; `workflow_start`, `workflow_advance`, and `workflow_finalize` remain saved-call compatibility. `material_*`, `verification_*`, and generic `agent(argv)` infrastructure are outside public discovery. Ordinary edits and tests need no duplicate material or verification bookkeeping.

## Read the result envelope before continuing

A successful response contains `ok`, `operation`, and its `result`. Failures contain `ok`, `operation`, and an `error` with these fields:

| Field | How to use it |
| --- | --- |
| `code` | Identify the violated input, identity, revision, or domain prerequisite |
| `message` | Read the concrete reason |
| `state` | Determine whether execution started or reached another recorded state |
| `retryable` | Learn whether the operation reports retry support |
| `next_action` | Follow the supported correction or recovery route |

A failed call is not permission to supply a guessed identity or broaden execution policy. On an uncertain response, retain the original logical operation key and identical content where the operation supports replay. If the intended request changes, it is a new operation.

Transport uses JSON-RPC on stdout and diagnostics on stderr. Named request content is limited to 64 KiB. JSON document arguments also have explicit limits: 64 KiB, nesting depth 16, 128 properties per object, and 1,024 items per array; null bytes and nonfinite numbers are rejected.

## Worked sequence: preserve a saved filter after reload

The following is an illustrative request for a user's web application, not a Neurath feature. Values in angle brackets must be replaced with actual returned values. Revision examples show types only; read the live revisions instead of assuming a fresh ledger.

First inspect `session_status`, `worktree_inspect`, and `task_list` as needed for the current work. Acquire the current worktree claim only when the authorized work requires it and the ownership state permits it. The task list supplies the native prompt source and existing work to reuse.

Define the observable goal through `task_define`:

```json
{
  "tasks": [
    {
      "key": "persist-saved-filter",
      "title": "Keep the saved filter after refresh",
      "goal": "Preserve the selected filter across save and reload.",
      "sources": [
        {
          "kind": "prompt",
          "reference": "<returned prompt reference>",
          "revision": "<returned prompt revision>"
        }
      ],
      "acceptance": [
        "The chosen filter survives saving and reloading the page.",
        "The restored value is displayed and applied to the results.",
        "Existing default-filter behavior remains covered."
      ],
      "dependencies": []
    }
  ],
  "expected_revision": 0,
  "key": "define-persist-saved-filter"
}
```

`tasks` accepts one to 64 definitions. Each needs all six fields shown. A definition accepts up to 31 caller-supplied sources, one to 32 acceptance conditions, and up to 64 dependencies. The runtime admits the native prompt provenance and adds its canonical evidence metadata.

Start the returned task with `task_start`:

```json
{
  "task_id": "<returned task id>",
  "expected_revision": 1,
  "expected_task_revision": 1,
  "key": "start-persist-saved-filter"
}
```

Use the actual list and task revisions from the preceding result. Reproduce save/reload through native tools, change the necessary code, and run the appropriate project check. When authorized and useful, delegate the API review with a bounded question and receive its result before relying on it.

If this reveals a separate necessary fix, call `task_define` for that follow-up before resolving the current task. Preserve the original requirement source. A later status prompt does not implicitly become the source for newly expanded work.

Resolve the observed result through `task_resolve`:

```json
{
  "task_id": "<returned task id>",
  "expected_revision": 2,
  "expected_task_revision": 2,
  "key": "resolve-persist-saved-filter",
  "status": "succeeded",
  "references": ["<actual reproduction or regression evidence reference>"],
  "summary": "Save and reload preserve the selected filter; the restored value is displayed and applied, and the default behavior check passed."
}
```

That summary is appropriate only after those observations actually exist. `references` requires one to 32 distinct nonempty references; the service preserves an owner report with `agent-report` assurance. For `failed` or `invalidated`, describe the actual outcome and its basis. Do not use a failure label merely to pass Stop.

## Keep the host plan consistent

Read the returned `native_todo` and submit its exact full argument object using the host's `update_plan` or `TodoWrite`. The native projection includes real outcome text because a host's completed visual state covers every terminal outcome. A display receipt proves native submission only. See the [task and TODO contract](task-todo-contract.md).

## Calls that require extra care

| Situation | Call contract and next observation |
| --- | --- |
| Task revision conflict | Reread `task_list`, reconcile current work, and use the returned revisions for the next intended operation |
| Missing native prompt or changed turn | Inspect current native state; use a real current or retained prompt source through a fresh invocation |
| Worktree release | Pass the actual `expected_lease_epoch` and `fencing_token` from the owned claim; preserve tokens as private runtime data |
| Explicit phase progress | Read `phase_current`, prepare evidence for the exact revision, then complete the matching phase |
| Review outcome | Consume the authenticated outcome for the exact review/candidate before relying on it; publication has separate scope and current-head checks |
| Independent provider run | Read actual models, create the revisioned plan, then run that plan and verify readiness; admission is not completion |
| Memory adoption | Preview, read if needed, and adopt the returned immutable reference with a distinct key and actual receiver revision after source quiescence |
| Delivery uncertainty | Inspect the participating message or owned run after the event/failure and follow its recovery route without changing its identity |

`phase_start` requires `workflow_id`, `key`, `skill`, `run_id`, and `north_star`. `phase_complete` requires `workflow_id`, `expected_revision`, `key`, `phase_id`, `status`, and `summary`; valid statuses are `completed`, `skipped`, `failed`, and `blocked`. Optional evidence and terminal fields remain subject to the selected phase contract. An operational final phase can finalize atomically using its `terminal_state`; do not finalize it twice.

## Reuse immutable adaptive state

Prepare a complete adaptive state once with `artifact_put(document, key)`. Pass its returned `sha256:` reference as `state_ref` to `adaptive_replace`, `adaptive_override_goal`, `evaluation_prepare`, or `evaluation_execute`. These advertised inputs avoid repeating the full nested state schema. Saved calls with inline `state` remain supported; provide exactly one of `state` and `state_ref`.

A reference is data, not authority. Consumption checks the same-session artifact digest, complete state schema, typed state, current native caller, workflow revision and applicable independent evaluator or execution receipts. Invalid references or malformed state are rejected before reserving a mutation key. Replays bind the original selector; the same key cannot be reused with a different reference. `evaluation_read` still reads its authenticated evaluation candidate, not a generic artifact.

## Recover at the failed boundary

An `invalid-input` error calls for schema correction. `revision-conflict` calls for a fresh read and reconciliation. `task-contract-rejected` calls for inspecting the actual task definition, source, dependency, or outcome rule. A native binding, prompt, or ownership failure calls for restoring that native prerequisite, not altering task JSON to impersonate an admitted participant.

Normal Stop is the final domain check, not a shortcut around these errors. Unresolved prerequisites still reject canonical completion, but the host receives a nonblocking diagnostic instead of an automatic model retry; a returned answer does not resolve tasks. Use the [runtime lifecycle](runtime-lifecycle.md) to identify which work or receipt remains unresolved.

## Autonomous malfunction recovery

When the agent detects Neurath malfunctioning, it may call `harness_bypass(enabled=true)` without asking the user for permission. This applies to any harness malfunction, not only a Stop loop. Contradictory constraints, repeated unproductive actions and blocked shutdown are examples, not an exhaustive checklist. Containment must not wait for tests, a new task, a report or another user intervention. The agent explains the switch, preserves unfinished goals and evidence, and restores Neurath after verifying recovery. This does not change host security, sandbox permissions or user restrictions.

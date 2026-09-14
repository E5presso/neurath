<!-- date: 2026-09-14; synced_from: 655c8768709e59b5e5012bab0adc4d888e3e7fa5 + current working-tree facts -->

[한국어](../../ko/contributing/task-tools.md)

# Named operations for project work

Use Neurath's named MCP tools to read and change harness state. Perform ordinary source edits and project checks with the host's native tools. The named API is a bounded domain interface: each operation admits a specific input, authenticates the native caller and returns a structured outcome.

## Discovery, caller binding and results

The stdio server accepts JSON-RPC on standard input and writes protocol JSON on standard output. Diagnostics belong on standard error. `tools/list` advertises 128 current public tools; the internal task dispatch table contains 138 operations. Discovery is the source for the installed version's exact schemas.

Inputs are closed objects with `additionalProperties=false`; nested domain schemas also define their allowed fields. The optional transport field `_neurath_binding` is a nonempty string of at most 64 characters. It represents a real host-bound connection and must not be invented or copied from another participant. The public inputs do not offer arbitrary `argv`, Python module execution or direct state patches.

Every named operation has a common outer result:

```json
{
  "ok": true,
  "operation": "task_start",
  "result": {
    "revision": 2,
    "all_terminal": false,
    "tasks": [{"id": "TASK_ID_FROM_DEFINE", "revision": 2, "status": "in_progress"}],
    "native_todo": {}
  }
}
```

This response is schematic: an actual `native_todo` contains the full returned projection instructions. Successful calls contain the operation-specific result. Failure contains `error` with `code`, `message`, `state`, `retryable` and `next_action`; some failures also retain a result describing the attempted execution. Read that state before deciding whether retry is appropriate.

Task mutations return compact list revision, `all_terminal`, task IDs/revisions/statuses and `native_todo`. They omit full definitions and result-report details. `task_list` returns the full ledger view, `current_prompt_source`, definition digests, result report references when present, `assurance`, `todo_projection` and `native_todo`. Reuse mutation results rather than immediately issuing a duplicate list read.

## Diagnose execution readiness before changing permissions

Execution tools report `execution-readiness-required` when a required installation, activation, ownership or policy-observation stage is not ready. The response identifies the failed stages. A running MCP package that differs from the installed distribution requires reconnecting that MCP host; repeating installation or changing permissions does not refresh an existing process. `session_status` gives the same recovery direction. When readiness passes but the observed execution policy is unsupported, `native-execution-required` remains a denial. Neither diagnostic authorizes transport replay, fabricated identity, ownership takeover or permission changes.

## Register, start and resolve a task

| Tool | Required input | Result or condition |
| --- | --- | --- |
| `task_list` | None | Read current list and display projection. No tasks yields `all_terminal=false`. |
| `task_define` | `tasks`, `expected_revision`, `key` | Append 1–64 definitions and return stable IDs and updated revisions. |
| `task_start` | `task_id`, `expected_revision`, `expected_task_revision`, `key` | Change a pending task to `in_progress`; dependencies must be terminal. |
| `task_resolve` | Start fields plus `status`, `references`, `summary` | Record `succeeded`, `failed` or `invalidated`; success requires terminal dependencies. |

List and task expected revisions are integers from 0 through 9,007,199,254,740,991. `task_id` is 1–128 characters; the operation key is 1–512 characters. Resolution takes 1–32 distinct nonempty references of at most 4,096 characters each and a nonempty summary of at most 4,096 characters.

Every definition supplies all six fields:

| Field | Exact input shape |
| --- | --- |
| `key` | Nonempty string, at most 512 characters; stable definition key within the session. |
| `title` | Nonempty string, at most 512 characters. |
| `goal` | Nonempty string, at most 16,000 characters. |
| `sources` | 0–31 objects, each with required `kind`, `reference`, `revision`; no extra fields. |
| `acceptance` | 1–32 nonempty strings, each at most 16,000 characters. |
| `dependencies` | 0–64 nonempty task IDs, each at most 128 characters. |

Source `kind` is `prompt`, `ticket` or `spec`. Its `reference` and `revision` are each 1–4,096 characters. The service preserves the native user prompt even when the caller supplies an empty source array. Supplied prompt references must match real stored native receipts.

For a new empty ledger, this definition uses no invented prompt receipt:

```json
{
  "tool": "task_define",
  "arguments": {
    "tasks": [{
      "key": "parser-empty-input",
      "title": "Handle empty parser input",
      "goal": "Empty input returns the documented empty result.",
      "sources": [],
      "acceptance": ["The empty-input regression passes.", "Existing valid-input behavior is preserved."],
      "dependencies": []
    }],
    "expected_revision": 0,
    "key": "define-parser-empty-input"
  }
}
```

Use revision 0 only when the current list is actually empty at that revision. Copy the returned task ID and revisions into the next call:

```json
{
  "tool": "task_start",
  "arguments": {
    "task_id": "TASK_ID_FROM_DEFINE",
    "expected_revision": 1,
    "expected_task_revision": 1,
    "key": "start-parser-empty-input"
  }
}
```

After the authorized edits and actual check, submit the result. The reference and numbers below illustrate their roles; replace them with the observed result and the previous operation's returned revisions.

```json
{
  "tool": "task_resolve",
  "arguments": {
    "task_id": "TASK_ID_FROM_DEFINE",
    "expected_revision": 2,
    "expected_task_revision": 2,
    "key": "resolve-parser-empty-input",
    "status": "succeeded",
    "references": ["tests/test_parser.py::test_empty_input"],
    "summary": "The empty-input regression and existing valid-input checks passed."
  }
}
```

The canonical result has `assurance=agent-report`: it is the authenticated owner's report. A test name alone is not an execution observation; the owner must describe the actual performed checks honestly. The [task and TODO contract](task-todo-contract.md) covers immutable terminal history, dependency ordering, native display receipts and the atomic Stop decision.

## Ownership and session inspection

| Tool | Input | Purpose |
| --- | --- | --- |
| `session_status` | Optional `detail`: `summary` (default) or `full` | Inspect current participation, readiness and ownership. |
| `session_inspect`, `turn_inspect`, `worktree_inspect` | No business fields | Read the relevant domain state before recovery or mutation. |
| `worktree_claim` | No business fields | Claim the actual caller's current worktree. |
| `worktree_release` | `expected_lease_epoch` (1–9,007,199,254,740,991), `fencing_token` (1–256 characters) | Release exactly the lease returned for this owner, under its release contract. |
| `worktree_isolation` | `issue_number` (1–2,147,483,647), `key`; optional `initialize=false` | Prepare the issue's isolated workspace under the supported contract. |
| `worktree_cleanup` | `workflow_id`, verified `base_branch`, verified `remote_ref`, `key` | Perform the contracted cleanup with ownership and Git-state checks. |

A claim is independent of installation and host activation. Do not infer a valid lease from a running model or from an old checkpoint. [Runtime lifecycle](runtime-lifecycle.md) explains release, cleanup reservation and resume.

## Phases for explicit skill workflows

Start with the actual skill contract and use its current IDs and labels. The common phase inputs are:

| Tool | Required fields | Optional fields and bounds |
| --- | --- | --- |
| `phase_start` | `workflow_id`, `key`, `skill`, `run_id`, `north_star` | Nonempty workflow/run IDs ≤256 characters, skill ≤128, key ≤512, north star ≤16,000. |
| `phase_current` | `workflow_id` | Returns current contract state and revision. |
| `phase_evidence_prepare` | `workflow_id`, `expected_revision`, `key` | `labels=[]`: up to 32 nonempty strings ≤16,000; `notes=[]`: up to 128 objects containing `label` (1–128) and `text` (1–16,000). |
| `phase_complete` | `workflow_id`, `expected_revision`, `key`, `phase_id`, `status`, `summary` | `phase_id`: 0–1000; status `completed`, `skipped`, `failed`, `blocked`; `reason=""`, `terminal_state=""`, `evidence_refs=[]`. |
| `phase_finalize` | `workflow_id`, `expected_revision`, `key`, `terminal_state` | Terminal state is a nonempty string ≤128 characters. |

Phase revisions use the same 0–9,007,199,254,740,991 range. In `phase_complete`, summary is 1–16,000 characters, reason at most 16,000, terminal state at most 128, and evidence references are at most 32 nonempty strings of at most 16,000 characters. The workflow contract determines whether a status, skip reason or terminal state is valid beyond these schema checks.

Use `phase_evidence_prepare` results for `evidence_refs`; labels are checked against the current phase. An operational final phase can use `terminal_state` to finish atomically. A workflow that needs separate finalization still uses `phase_finalize`. Reading a skill or writing a sentence that says “passed” does not advance its state.

`workflow_start`, `workflow_advance` and `workflow_finalize` remain dispatch-compatible for saved callers but are not publicly discovered. Current clients use the phase family.

## Continue another provider's unfinished work

`memory_pull` exposes `list`, `preview`, `read`, and `adopt`. The receiver lists sessions and previews an exact source before choosing adoption. Adoption uses the returned immutable `reference`, current receiver `expected_revision`, and a different stable key from preview. It can transfer unfinished tasks and their worktree lease only after source activity has settled. See [the full input and paging reference](provider-continuity.md).

`task_list` also exposes `all_succeeded` and `unsuccessful_task_ids`; `all_terminal` alone does not establish goal achievement. Definitions require native prompt provenance, and newly encountered prompt sources require explicit selection. The [task contract](task-todo-contract.md) explains these outcome and intake rules.

## Other domains and compatibility

The [capability map](capability-map.md) lists every public tool family and implementation owner. [Agent reference](agents-reference.md), [model planning](model-planning-mcp.md), [collaboration](collaboration-contract.md), [memory](memory-reference.md), [installation](installation.md), [releases](releases-reference.md) and [reporting](reporting-reference.md) describe their domain contracts.

Ordinary peer work uses `collaboration_assign`, `collaboration_accept` and `collaboration_report`. Message acknowledgement requires a full-body read and does not complete that assignment. Batch sends and batch acknowledgements use the advertised closed schemas; do not mix scalar send fields with the `messages` array. Actual child delegation and evaluation need verified native lineage in addition to a message.

Material and registered-verification operations, and the generic `agent(argv)` gateway, are saved-call compatibility surfaces. They are absent from current public discovery. They are not mandatory wrappers around ordinary native editing or checking.

`harness_bypass` is the exception to normal binding admission: `enabled=true` or `false` changes the current worktree switch; omission or `null` reads it. It requires neither a native binding nor a worker slot. It preserves history and host permissions. Other MCP operations require authentic binding and are unavailable during bypass.

## Diagnose before changing the request

| Failure | Meaning | Next action |
| --- | --- | --- |
| `revision-conflict` | The list or task revision changed. | Read the latest ledger and decide a new request with its actual revisions. |
| `task-contract-rejected` | Invalid task input, unsettled dependencies, immutable terminal history or another domain condition. | Read the message and fix that condition; do not patch stored state. |
| `native-turn-changed` | Transaction admission lost the native prompt or active connection. | Re-enter through the real current native turn, then inspect state. |
| Key reused with different input | One idempotency identity was assigned to different requests. | Keep the original request's identity; use a new key for new input. |
| Provider or delivery admission without completion | Work or transport is still outstanding. | Follow events, full-body readback and the relevant recovery contract. |

A retryable error is permission to follow the operation's recovery contract, not to widen host rights. Preserve uncertain outcomes until the actual result or supported recovery resolves them.

Schema and dispatch: [task schema](../../../src/neurath/runtime/task_schema.py), [task definitions](../../../src/neurath/runtime/task_ledger_tasks.py), [runtime dispatch](../../../src/neurath/runtime/tasks.py), [MCP server](../../../src/neurath/agents/mcp.py). Regression coverage: [communication MCP](../../../tests/test_communication_mcp.py), [task tools](../../../tests/test_task_tools.py), [MCP guidance](../../../tests/test_mcp_guidance.py).

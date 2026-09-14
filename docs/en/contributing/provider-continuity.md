<!-- updated: 2026-09-14; synced_from: 243400e58ca74c7fd79bcdd86b488953fa743b97 -->

# Continue the unfinished work from a receiving session

[한국어](../../ko/contributing/provider-continuity.md) · [Contributor start](index.md)

A coding session may end before the user gets the result. In the hypothetical web application, the agent may have confirmed that the save API persists the filter but still need to fix and verify the reload path. The next agent needs both the investigation and a valid right to continue editing. Neurath's `memory_pull` lets the receiving session obtain the retained work and, when safe, adopt its unfinished tasks.

## What is being carried forward

**Context** is information presented to the agent for its current reasoning. **Memory** is attributed project information retained across sessions. A **session** is the native host interaction that produced those records. A **checkpoint** is an agent-authored handoff summary with decisions and next steps. A **transcript** is the native host's JSONL record of messages and tool events. A **pull** is the receiver's explicit retrieval of another session's retained work; adoption is the later ownership-changing step.

The receiver reads source tasks and process state in the shared SQLite database, saved memory, communications, and the exact registered native JSONL. The source does not need to produce a final checkpoint or push a handoff. Already persisted decisions remain available even when it could not finish gracefully. A transcript can recover additional visible work, but no operation can guarantee recovery of provider content that was never persisted.

Sharing is local to the Git common directory. Linked worktrees and Codex/Claude sessions of that project can share records; independent clones and different machines do not synchronize automatically. The receiving verified native root must be in the original source worktree to adopt its work. It keeps its own native settings and identity.

App affiliation is a separate diagnostic: `session_status.app_project` reads the app-owned local `thread-project-assignments` to find this session’s assignment, `local-projects` to verify the matching local project, and `projectless-thread-ids` to distinguish an explicitly projectless session. The read is capped at 16 MiB and returns only relevant affiliation fields. It does not change app state, observe remote UI, grant authority, or adopt work. See [the source reader](../../../src/neurath/hosts/app_projects.py).

## Preview the exact source before changing ownership

1. Call `memory_pull(action="list")` to discover candidates. The default limit is 20 and the maximum is 50.
2. Select the observed `source_host` and `source_session`. Call `preview` with a stable key. Never guess a session from a familiar title.
3. Inspect the returned source, task state, native observation, and snapshot `reference`. Read the rest if the preview is limited.
4. Reconcile the original user acceptance, unfinished work, unknown outcomes, and any source restrictions before considering adoption.

These operations have `authority="reference-only"`. Preview creates an immutable receiver-owned snapshot; it does not move the lease or make earlier work yours. The registered source JSONL, or its exact Codex archive relocation, is the only transcript source. Private reasoning and known credentials are omitted, while positions, digests, source attribution, and omission notices are preserved. There is no broad scan across conversations.

## Read large snapshots without losing the boundary

Both preview and read responses fit within 8,000 UTF-8 bytes. A `read` fragment contains at most 3,000 characters and can be shortened further to fit the byte bound. Its `offset` and `next_offset` count characters. They are different from transcript byte positions used by `before_offset`.

```json
{
  "action": "read",
  "reference": "<reference returned by preview>",
  "offset": 0
}
```

Follow each returned `next_offset` until it is `null`. `json_fragment` is part of the saved snapshot document, so a single page need not be valid standalone JSON. A limited preview supplies `read_remaining` with the correct reference. Reading that document recovers the full saved snapshot, not omitted source material.

A preview memory page contains at most 64 entries; individual memory content is capped at 4,096 characters and carries a truncation indication when needed. `memory_before` and `before_offset` select earlier retained memory and transcript portions with a new preview request. `scan_transcript=false` suppresses transcript body inclusion; native identity, source state, and pending-execution checks still apply.

## Adopt only a stopped, settled source

Before adoption, the source must be quiescent: the registered transcript is complete, no tool/process outcomes remain pending, and the native turn is closed or the journal records disconnection. Native children, provider executions, and peer assignments must also be settled. A yielded shell process without a later exit observation is unsettled even if the source stopped speaking.

Read the receiver's `task_list` and use its returned revision. Then call:

```json
{
  "action": "adopt",
  "reference": "<the inspected immutable preview reference>",
  "expected_revision": 0,
  "key": "saved-filter-adopt-1"
}
```

Here `0` is only illustrative: replace it with the actual receiver revision. Use a distinct key from preview. Adoption checks that the source task/process state, transcript observation, communications, and lease still match the preview. It also checks the current receiving task revision. Any changed basis requires a new preview and reconciliation, not a forced takeover.

The transaction creates receiver-owned IDs for unfinished tasks, remaps dependencies, transfers the source-owned worktree lease, and marks the source as superseded. At most 64 unfinished tasks can be adopted. Completed source history stays attributed to the source. Partial import must roll back every domain. The returned claim is the current claim; old fencing tokens no longer authorize writes.

A migrated source cannot resume task mutations or reclaim the worktree, even after the receiver later releases its lease. Adoption moves continuation responsibility rather than duplicating two active owners. It does not copy permissions or convert a previous failed attempt into cancellation of the user's requirement.

## Resolve the obstacle that the tool actually reports

| Condition | Consequence and recovery |
| --- | --- |
| Source is active or execution is unsettled | Preview can remain useful; adoption is unavailable until the real execution settles. |
| Source state, transcript, or lease changed | Prepare a fresh snapshot and reassess it. |
| Receiver revision changed | Read the receiver ledger again and reconcile before a new adoption call. |
| Different worktree or a foreign claim | Receive in the original worktree under valid ownership; do not manufacture a claim. |
| Snapshot belongs to another receiver | That reference cannot be adopted or read as this receiver. |
| Legacy workflow lacks task continuation contract | Reference inspection remains available; task adoption is not established. |
| Unknown previous process outcome | Keep it unknown and settle it through its authorized execution owner. |

Once adopted, select the returned unfinished task with current task revisions, complete the reload fix and verification, and resolve the original acceptance conditions. Release the adopted lease only when authorized and using its actual returned values. The fact that memory was read, imported, or summarized is not evidence that the filter now survives refresh.

## Evidence for the mechanism

[src/neurath/memory/migration.py](../../../src/neurath/memory/migration.py) implements snapshots, bounds, and atomic adoption. `migration_transcript.py` limits native transcript recovery. Source mutation and claim fences also live in [src/neurath/_assets/scripts/agent_harness/task_service.py](../../../src/neurath/_assets/scripts/agent_harness/task_service.py) and `worktree_registry.py`.

[tests/test_memory_pull.py](../../../tests/test_memory_pull.py) covers unchanged-source requirements, task and lease transfer, rollback, dependency remapping, and the persistent source fence. [tests/test_memory_pull_mcp.py](../../../tests/test_memory_pull_mcp.py) covers individually parameterized native-bound pulls without source checkpoints; [tests/test_migration_transcript.py](../../../tests/test_migration_transcript.py) covers transcript boundaries. Individual bidirectional native cases and simulated billing-exhaustion cases are bounded evidence. They are not universal production proof or a guarantee of perfect semantic continuity across every provider interruption.
## Named input reference

The tables below are the current named-tool input contract. Nested required fields are required when their parent object or array item is supplied. Schema acceptance is only the first check; native identity, ownership, source, revision, and operation-specific prerequisites still apply. The host supplies `_neurath_binding`; do not synthesize it.

Every response has `ok` and `operation`. A successful call carries its canonical `result`; a failure carries `error.code`, `error.message`, `error.state`, `error.retryable`, and `error.next_action`. An `ok` envelope establishes the stated operation only, not the user goal. Preserve returned IDs and revisions for dependent calls.

### `memory_pull`

| Field | Presence / default | Type and limits |
| --- | --- | --- |
| `action` | optional; default `"list"` | text: `"list"`, `"preview"`, `"read"`, `"adopt"` |
| `source_host` | optional; default `"codex"` | text: `"codex"`, `"claude-code"` |
| `source_session` | optional; default `""` | text; 0–256 characters |
| `reference` | optional; default `""` | text; 0–71 characters |
| `key` | optional; default `""` | text; 0–512 characters |
| `expected_revision` | optional; default `0` | integer; 0–9007199254740991 |
| `scan_transcript` | optional; default `true` | boolean |
| `limit` | optional; default `20` | integer; 1–50 |
| `before_offset` | optional; default `0` | integer; 0–9007199254740991 |
| `offset` | optional; default `0` | integer; 0–9007199254740991 |
| `memory_before` | optional; default `0` | integer; 0–9007199254740991 |

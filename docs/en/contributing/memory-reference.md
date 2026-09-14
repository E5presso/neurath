<!-- updated: 2026-09-14; synced_from: 243400e58ca74c7fd79bcdd86b488953fa743b97 -->

# Remember the investigation and validate useful lessons

[한국어](../../ko/contributing/memory-reference.md) · [Contributor start](index.md)

When an agent returns to the saved-filter investigation, it should be able to recover what the save API did, which reload behavior remains unexplained, and which verification still needs to run. Neurath retains attributed work records and presents a bounded selection to later sessions. It also recognizes some successful command recoveries and tests whether they are reliable enough to offer as guidance.

This page describes ordinary memory and learning. Moving unfinished tasks and write ownership into a different root uses [the separate pull-and-adopt procedure](provider-continuity.md).

## Understand what is stored and what is shown

A **session** is a native host interaction. **Memory** is the project's retained information from those interactions; **context** is the selected information currently shown to an agent. A **checkpoint** is an explicit handoff report written by the agent. A **transcript** is the host's underlying JSONL history, which can contain more visible detail than ordinary recall includes.

Project memory uses a SQLite runtime database selected by Git common directory. Linked worktrees and Claude/Codex sessions of that local project share the store. Separate clones and computers do not automatically share it. Attribution keeps host, session, event identity, sequence, kind, and relevant metadata attached to records. Current user instructions, current source, and current ownership remain authoritative when recalled material disagrees.

Validated hooks record the user request at `UserPromptSubmit`, observed command events and their actual process outcomes, and eligible assistant/workflow reports at `PreCompact`, `Stop`, or `SessionEnd`. Reports remain agent reports. Text printed by a command, including JSON claiming an `exit_code`, is not native execution metadata. Private reasoning is excluded; common credential patterns are redacted before persistence. This is pattern-based redaction, so private project content still belongs in local records rather than public reports.

At `SessionStart`, the host injects at most 3,000 bytes of selected memory context. Learned guidance is a separate contribution, capped at 6,000 bytes and twelve rules. Ordinary recall does not import Newsroom article bodies. Agents read relevant articles explicitly and retain their attribution.

## Ask for a specific memory or save a handoff

`memory_recall(query, limit)` finds relevant project history. The default limit is 12 and the maximum is 100. The underlying explicit context renderer has a 12,000-byte default, distinct from the smaller automatic SessionStart injection. Read the source and age of the returned observations, then verify facts that can have changed.

`memory_checkpoint(summary, key, decisions, next_steps, lessons, status)` stores a handoff. The summary and key are required; lists default to empty. Each list accepts up to 32 nonempty strings. `status` is `active`, `paused`, `completed`, or `blocked`, with `paused` as default. Use the same key and identical content for an uncertain retry.

For the filter defect, a useful checkpoint could say that the API stores the selected value, the reload path still needs investigation, and the next verification must exercise a fresh page load. Include actual evidence references when available. A `completed` checkpoint means the agent reported completion; it does not resolve a task, release a claim, finalize a review, or supply an extra ordinary completion vote.

The runtime can request a checkpoint after meaningful work when a handoff is due. The agent must supply the factual summary; the request does not turn missing work into a completed task. Pull can use persisted SQLite and registered transcript records even if that final summary was never written.

## A reflection is not yet validated guidance

“Use the project's environment to run tests” is a reflection the agent might place in `lessons`. A learned command recovery requires stronger evidence. Suppose the filter investigator runs the same test selector unsuccessfully because the test runner is missing, then successfully runs that operation through the project's environment. The implementation's test fixture uses `pytest -q` followed by `uv run pytest -q`; in a real project, retain the actual command and selector observed there.

The learning engine associates failure and changed successful recovery only within the same session, worktree, operation family, and verification contract. Running a different test, printing a success message, an unrelated green command, or returning an unknown process outcome does not create that association.

| State | How it is reached | What later agents receive |
| --- | --- | --- |
| `candidate` | A qualifying failed command is followed by an observed successful alternative. | No promoted guidance yet. |
| `trial` | A complete matching configured project check passes in the source session. | Bounded trial guidance, explicitly awaiting independent use. |
| `active` | A different session was actually shown the guidance, ran the exact recovery successfully, and passed the matching project check. | Validated scoped guidance while the verifier remains applicable. |
| `reverted` | The recovery regresses, or a check fails after relevant trial/active use. | The withdrawn guidance is no longer offered. |
| `stale` | The originating worktree's verification contract changed. | Old guidance is withheld until new evidence supports it. |

**Exposure** means a particular lesson was actually included in the guidance delivered to a session. Merely storing it or listing it is insufficient for trial credit. The recovery must be executed unchanged as a standalone command so the native exit outcome remains observable. A successful run in the original session, or in a different session that never received the guidance, cannot promote a trial.

A complete check receipt ties together the configured verifier digest, worktree fingerprints, output digest, actual exit code, timeout state, and passed result. Missing or incompatible evidence cannot admit a candidate into trial. A different linked worktree's check does not arbitrarily invalidate the original worktree's guidance.

## Automatic maintenance follows evidence already produced

At Stop, due learning can request the authorized project-registered verification and then a factual handoff. It does not run unrelated experiments or start unattended model sessions. If the check is unavailable, forbidden, failed, or deferred, the state remains unvalidated and no automatic duplicate retry loop is created.

Use `learning_status` for current strategies, `learning_pending` for due checks, and `learning_history(strategy_id)` for the transition record. `learning_defer(reason, key)` records why the specific pending observation cannot be checked now. New qualifying evidence can make checking due again. A new valid failure/recovery pair can reset a candidate, reverted, or stale strategy, clearing old exposure records; promotion must then be earned again.

Learning changes stored guidance, not model weights, permissions, or repository rules. The three activities are deliberately separate: reflection records a useful idea, execution learning validates a scoped recovery, and `memory-to-rules` proposes durable project guidance for an authorized, privacy-reviewed repository change. Its source skill identifier is `promote-memory`; a proposal alone does not edit the repository.

## Source and useful regression cases

Memory persistence and selection are in [src/neurath/memory/store.py](../../../src/neurath/memory/store.py); hooks are in `hooks.py`; recovery learning is in `learning.py`. The runtime's named memory and learning operations are defined in [src/neurath/runtime/task_schema.py](../../../src/neurath/runtime/task_schema.py) and `maintenance_tasks.py`.

[tests/test_project_memory.py](../../../tests/test_project_memory.py) and [tests/test_memory_hooks.py](../../../tests/test_memory_hooks.py) cover retention, sharing, bounded context, and hook observations. [tests/test_learning.py](../../../tests/test_learning.py) covers candidate → trial → active → reverted, changed verifiers, unrelated commands, selector mismatches, incomplete receipts, actual exposure, and deferred checks. These are inspectable implementation cases; a stored lesson must still be read in its own scope before using it to finish the filter fix.
## Named input reference

The tables below are the current named-tool input contract. Nested required fields are required when their parent object or array item is supplied. Schema acceptance is only the first check; native identity, ownership, source, revision, and operation-specific prerequisites still apply. The host supplies `_neurath_binding`; do not synthesize it.

Every response has `ok` and `operation`. A successful call carries its canonical `result`; a failure carries `error.code`, `error.message`, `error.state`, `error.retryable`, and `error.next_action`. An `ok` envelope establishes the stated operation only, not the user goal. Preserve returned IDs and revisions for dependent calls.

### `memory_recall`

| Field | Presence / default | Type and limits |
| --- | --- | --- |
| `query` | optional; default `""` | text; 0–16000 characters |
| `limit` | optional; default `12` | integer; 1–100 |

### `memory_checkpoint`

| Field | Presence / default | Type and limits |
| --- | --- | --- |
| `summary` | required | text; 1–16000 characters |
| `key` | required | text; 1–512 characters |
| `decisions` | optional; default `[]` | array; 0–32 items; text; 1–16000 characters |
| `next_steps` | optional; default `[]` | array; 0–32 items; text; 1–16000 characters |
| `lessons` | optional; default `[]` | array; 0–32 items; text; 1–16000 characters |
| `status` | optional; default `"paused"` | text: `"active"`, `"paused"`, `"completed"`, `"blocked"` |

### `learning_status`

No agent-supplied input fields.

### `learning_pending`

No agent-supplied input fields.

### `learning_history`

| Field | Presence / default | Type and limits |
| --- | --- | --- |
| `strategy_id` | required | text; 1–128 characters |

### `learning_defer`

| Field | Presence / default | Type and limits |
| --- | --- | --- |
| `reason` | required | text; 1–2000 characters |
| `key` | required | text; 1–512 characters |

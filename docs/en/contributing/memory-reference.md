<!-- date: 2026-09-14; synced_from: 655c8768709e59b5e5012bab0adc4d888e3e7fa5 + current working-tree facts -->

[한국어](../../ko/contributing/memory-reference.md)

# Context that survives a session

Project memory helps the next agent recover decisions, observations, and unfinished work. Its records are attributed context. The current request, current source, and current ownership determine what the agent may do. A remembered approval or a completed handoff note cannot grant a new caller authority.

## Choose the right store

| Need | Interface | Meaning |
| --- | --- | --- |
| Recover previous decisions and work | `memory_recall` | Cross-session project history with source information |
| Leave a concise handoff | `memory_checkpoint` | An agent's summary, decisions, next steps, and lessons |
| Keep the latest facts of this session | `enclave_read`, `enclave_set`, `enclave_delete` | Bounded working state with digest-based concurrency checks |
| Inspect command recovery guidance | `learning_status`, `learning_pending`, `learning_history` | Observed strategies and their validation history |
| Turn recurring knowledge into a project rule | `memory-to-rules` skill | A separately reviewed, authorized rule change |
| Explore source relationships | `graphify` skill | An exploratory graph whose conclusions need source checks |

Mutable state uses the shared `.neurath/local/runtime.sqlite3` below the Git-common-derived control root. Linked worktrees share project memory; unrelated clones and computers do not synchronize automatically. Domain namespaces keep memory, session state, and other runtime records distinct. Installation plans, original-file backups, and journals still have their own private file storage.

## Automatic capture and bounded recall

Validated root host events record user requests and observed commands. `UserPromptSubmit` saves the request, including steering within a turn. Tool events retain the observed command and native outcome metadata. On `PreCompact`, `Stop`, and `SessionEnd`, the latest eligible assistant text can become an `agent-report`; workflow snapshots remain `reference-only`. Private reasoning channels are excluded.

| Context path | Limit | Trigger |
| --- | --- | --- |
| Automatic project-memory injection | 3,000 bytes | `SessionStart` only |
| Explicit `ProjectMemory.context` rendering | 12,000 bytes by default | An explicit internal context request |
| Learned guidance | At most 12 rules and 6,000 bytes | Separate guidance added during session startup |
| Named recall | `limit` defaults to 12; allowed 1–100 | `memory_recall` |

`UserPromptSubmit` does not reinject the memory block. Do not interpret the explicit 12,000-byte default as the automatic startup budget. Commands or conversation never observed and saved cannot be reconstructed after a crash. Already committed records remain available without a final checkpoint.

```json
{"query":"remaining work on export validation","limit":8}
```

Pass this input to `memory_recall`. Read the source and session attribution of relevant results, then inspect current code and checks before reusing a decision. Common credential patterns are redacted recursively, but semantic privacy review is still necessary before publishing anything derived from memory.

## Pull context and adopt unfinished work

`memory_pull` is a receiver-initiated continuity operation alongside ordinary recall. `list` finds source sessions, `preview` creates an immutable snapshot of an exact source, and `read` pages through that snapshot. Only `adopt` imports unfinished tasks and transfers their worktree lease after source execution has settled. A source checkpoint or final context push is not required.

The snapshot combines SQLite tasks, memory, and peer results with available user-visible content from the registered native transcript JSONL. Source attribution and offsets are retained; private reasoning and recognized credentials are excluded. Saved text remains reference material and cannot prove an unobserved tool result. Provider data that was never persisted cannot be guaranteed recoverable.

[Provider continuity](provider-continuity.md) describes inputs, paging, quiescence checks, atomic adoption, and source resumption fencing. Importing a recovery example does not promote it to active learned guidance: the existing source and independent-session checks below still apply.

## Record a usable handoff

The following is input to `memory_checkpoint`. It describes a fictional project task, not a Neurath export feature.

```json
{
  "summary":"Export validation handles an empty collection; the integration case remains open.",
  "key":"export-validation-handoff-1",
  "decisions":["Keep the existing public response format."],
  "next_steps":["Run the authorized integration case against the updated serializer."],
  "lessons":["An empty collection needs its own observed result."],
  "status":"paused"
}
```

`summary` and `key` are required. The three list fields default to empty arrays and allow up to 32 entries each. `status` is `active`, `paused`, `completed`, or `blocked`; its default is `paused`. Use a stable key for the same operation. A checkpoint marked `completed` remains an owner report; it does not resolve task-ledger entries, release a claim, certify a test, or finalize an explicit review.

For latest session facts, first call `enclave_read` with `{}`. Supply the returned digest as `expected_digest` when setting or deleting a fact. For example, `enclave_set` takes `fact_key`, `value`, `expected_digest`, and `key`. On a digest conflict, reread and reconcile the concurrent change rather than replacing the expected value with a guess.

## Learn an execution recovery

Learning connects failure and recovery for the same operation and selectors. For example, `pytest tests/test_export.py` and `uv run pytest tests/test_export.py` can describe the same selected test under a corrected environment. Running a different test does not establish recovery.

1. An observed failure and successful equivalent alternative produce a candidate.
2. A successful configured project check in the source session allows trial guidance.
3. A different session must actually receive the guidance, use the exact recovery, and pass the matching check before promotion to active guidance.
4. A recovery failure or subsequent project-check failure withdraws trial or active guidance. A change to the verification contract in the worktree where recovery was originally observed makes the guidance stale; a different check in another linked worktree does not invalidate it.

A newly observed instance of the same failure and successful recovery clears its previous exposure records and returns a `reverted` or `stale` strategy to `candidate` for validation again.

The process outcome supplied by the native host is authoritative. A command printing JSON containing `exit_code: 0`, a copied success report, an unknown outcome, or a different selected test cannot establish success. Standalone execution preserves the original exit status.

When a configured check is missing, unavailable, or forbidden, retain unvalidated guidance with a reason. Use `learning_pending` to inspect outstanding validation and `learning_defer` with `reason` and a stable `key` to record deferral. Repeating the same failed check without changed evidence adds no validation. `learning_history` requires the returned `strategy_id` and exposes the strategy's progression.

Learning is active-session behavior; it neither edits policy or permissions nor launches unattended model sessions. A project rule change belongs to the separate `memory-to-rules` workflow.

## Implementation and checks

Capture and authority boundaries are implemented in [host memory hooks](../../../src/neurath/memory/hooks.py), [project memory](../../../src/neurath/memory/store.py), [transcript synchronization](../../../src/neurath/memory/transcript.py), and [learning](../../../src/neurath/memory/learning.py). Latest-session concurrency belongs to [EnclaveStore](../../../src/neurath/_assets/scripts/agent_harness/enclave_store.py).

[Project-memory tests](../../../tests/test_project_memory.py) cover shared-worktree behavior, source replay conflicts, limits, redaction, and recovery without a checkpoint. [Learning tests](../../../tests/test_learning.py) cover exposure, different-session promotion, invalid or forged outcomes, deferral, contract changes, and withdrawal. These checks establish their tested boundaries; actual host activation requires native observations described in [validation](validation.md).

See [the skill reference](skills-reference.md) for rule promotion and [the agent reference](agents-reference.md) for session and ownership recovery.

<!-- date: 2026-09-14; synced_from: 655c8768709e59b5e5012bab0adc4d888e3e7fa5 + current working-tree source -->

# Continue interrupted work with another provider

[한국어](../../ko/contributing/provider-continuity.md)

When a provider stops before finishing, the receiving session can retrieve its saved context and take over the unfinished work. `memory_pull` reads the shared SQLite records and, when requested, the exact registered native transcript. It does not require a final checkpoint or context push from the source.

The receiver runs under its own native root in the original source worktree. It first reads a preview, then adopts work only after the source's execution has settled. For ordinary user requests, see [resume from recorded decisions](../usage/memory.md).

## Keep execution settings and work ownership separate

An independent `provider_run` uses `inherit` by default. To preserve the receiving provider's own existing defaults, hooks, and tool rules, explicitly authorize `target-native` and use that mode in both the plan and execution. Model choice remains a separate plan field. The created session's actual model, policy, activation, and ownership must still be checked.

`memory_pull` does not change the receiver's settings or copy source credentials. Its adoption step transfers unfinished tasks and the worktree lease. Selecting `target-native` alone transfers neither. See [model planning](model-planning-mcp.md) and [provider transports](provider-transports.md) for creation and policy validation.

## Find and preview the source

List candidate source sessions in the same Git project:

```json
{"tool":"memory_pull","arguments":{"action":"list","limit":20}}
```

Choose the exact returned source host and session. `source_host` is `codex` or `claude-code`; `limit` defaults to 20 and cannot exceed 50. The identifiers below are placeholders for actual returned values, not identities to invent.

```json
{"tool":"memory_pull","arguments":{"action":"preview","source_host":"codex","source_session":"SOURCE_SESSION_FROM_LIST","key":"continuity-preview-1"}}
```

Preview returns a `reference` plus source tasks, memory, communications, and transcript observations. It binds the source ledger, process, memory and communications state, registered transcript observation, and worktree lease basis into an immutable snapshot owned by the receiver. Reading it does not transfer ownership. Preview can help diagnose a source that is not yet safe to adopt.

## Read the available context in bounded pieces

The preview response is bounded to 8,000 UTF-8 bytes so the receiver can obtain its reference before taking ownership, without opening a host tool-output file through the shell. The complete snapshot is preserved. Use `read` to retrieve it in fragments:

```json
{"tool":"memory_pull","arguments":{"action":"read","reference":"RETURNED_PREVIEW_REFERENCE","offset":0}}
```

Read returns `json_fragment`, `next_offset`, and `total_characters`. Offsets are character positions, not byte offsets. Each fragment contains at most 3,000 characters and is shortened further when needed to keep the complete response within 8,000 UTF-8 bytes. Continue with the returned `next_offset` until the snapshot is read.

| Input | Purpose |
| --- | --- |
| `before_offset` | Request an earlier page of registered JSONL records; use the returned `earlier_offset` for the next preview |
| `memory_before` | Request an earlier SQLite memory page using the returned cursor |
| `scan_transcript:false` | Omit transcript content; native identity and unsettled-execution checks still apply |

A memory page contains at most 64 entries; individual memory content is limited to 4,096 characters and marked when shortened. Large transcript records can be represented by an omission notice, original location, and digest. Reading the full saved snapshot does not reconstruct content that was omitted before it was stored.

The transcript reader uses the registered JSONL file, or its exact Codex archive relocation, rather than scanning unrelated conversations. It excludes private reasoning and recognized credentials, retains source positions and digests, and treats recovered text as reference material. A saved statement of success is not evidence of an unobserved tool result. Content the provider never persisted cannot be guaranteed recoverable.

## Adopt only after source execution has settled

Use the preview's actual `reference` and the receiver's current task-list revision. The example revision `0` applies only to a receiver whose observed list revision is zero.

```json
{"tool":"memory_pull","arguments":{"action":"adopt","reference":"RETURNED_PREVIEW_REFERENCE","expected_revision":0,"key":"continuity-adopt-1"}}
```

Preview and adoption use different stable keys. Reuse a key only for the same operation and unchanged input. Adoption rechecks source quiescence, task and process state, transcript observation, and lease. A changed source requires a fresh preview, not a forced takeover.

Unobserved tool or process outcomes, active children, unsettled provider jobs, or peer assignments prevent adoption. Retain the preview and the reason when these conditions are unresolved. The interface has no force-takeover option.

On success, `status:"adopted"` is returned with `task_mapping`, imported `tasks`, the new `claim`, and `source_terminal_tasks`. Up to 64 unfinished tasks receive receiver-owned IDs with dependencies remapped. Terminal history and its evidence remain attributed to the source.

Task import, lease transfer, and the source migration fence commit atomically. A migrated source cannot resume mutation or reclaim the worktree, even after the receiver releases its own lease. This protects against both sessions continuing the same writes. The receiver retains the original goals and completion conditions; changing providers does not weaken them or turn a prior attempt's failure into user cancellation.

## Diagnose the boundary that has not been satisfied

| Observation | Next step |
| --- | --- |
| Source still has unsettled execution | Establish the actual tool, child, provider, or peer outcome before adoption |
| Source state or transcript changed after preview | Obtain a new preview and review its changed basis |
| Preview response was shortened | Read the saved snapshot with its returned reference and cursor |
| Original data was never saved | State the missing context; do not claim complete reconstruction |
| Native project metadata changed | Check desktop project membership separately; CLI-created Codex session association remains unresolved |
| Updated files but an older MCP connection is still running | Reconnect that connection and check which tools and behavior are active |

`provider_recover` restores the issuer's recorded provider execution. `memory_pull` lets a different native receiver adopt available context and work; it does not impersonate or resume the source. Ordinary [project memory and learning](memory-reference.md) remain available, and imported recovery examples still need the existing validation process before becoming active guidance.

## Implementation and verification scope

[Migration](../../../src/neurath/memory/migration.py) owns snapshots and atomic adoption. [Transcript recovery](../../../src/neurath/memory/migration_transcript.py) owns registered-log lookup and bounded extraction. [The task schema](../../../src/neurath/runtime/task_schema.py) defines inputs, and [provider policy](../../../src/neurath/runtime/provider_policy.py) handles target-native settings.

[Adoption tests](../../../tests/test_memory_pull.py), [MCP tests](../../../tests/test_memory_pull_mcp.py), [transcript tests](../../../tests/test_migration_transcript.py), and [target-policy tests](../../../tests/test_target_native_policy.py) cover deterministic behavior. Native checks cover pull in both directions through adoption, task completion, lease release, and preservation of the existing file. Simulated quota exhaustion does not demonstrate an actual billing-limit event or universal production readiness. Keep delegation, goal-reminder, and source-resumption-fencing evidence attached to the candidate on which each was observed. See [validation](validation.md) for these evidence boundaries. No check establishes perfect semantic recovery or recovery of data the provider never stored.

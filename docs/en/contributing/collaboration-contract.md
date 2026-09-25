<!-- updated: 2026-09-14; synced_from: 243400e58ca74c7fd79bcdd86b488953fa743b97 -->

# Share findings and delegate bounded work

[한국어](../../ko/contributing/collaboration-contract.md) · [Contributor start](index.md)

A second agent is useful when it has relevant knowledge or can investigate a separate question. Neurath gives that cooperation durable messages and explicit ownership. In the running example, the user's web application loses a saved filter after refresh. The current agent checks how the page restores the value while a peer investigates API storage and responses. A useful collaboration result says which question was answered, what was observed, and what remains for the original owner to verify.

## Choose the relationship before sending work

A **peer** is an existing independent native session. Discover a peer before addressing it; its own user instructions still govern what it can do. A **native child** is a direct child of the current session with host-attested lineage. A **provider session** is a new independent native root whose execution Neurath supervises. These relationships have different creation and reporting paths.

`collaboration_register(name, summary)` describes the current native participant. `collaboration_discover(query, limit)` searches the same local Git project and returns exact addresses. For example, search for saved-filter persistence before asking a peer whether the API stores the selection. An address is a destination, not authority to make that peer edit files. Registration, discovery, and assignment acceptance do not confer a worktree claim.

Linked worktrees share this project's local communication store through their Git common directory. Independent clones and different computers do not acquire a shared conversation merely because their repository URLs match.

## Use a message for a question and an assignment for work

`collaboration_send` sends a question, proposal, update, or result. Supply either `to`, `message`, and `key`, or a `messages` batch. The forms cannot be mixed. A batch accepts up to 32 items, each with up to 32 distinct recipients; after fan-out the request is limited to 100 deliveries and 262,144 UTF-8 body bytes. A batch body is capped at 32,768 UTF-8 bytes. Retrying an uncertain send keeps its key and identical content.

`collaboration_assign(to, message, key)` records an authorized assignment to a discovered peer. The receiver uses `collaboration_accept(task_id)` in its actual native turn; this emits `started`. The receiver's turn is then bound to the lifecycle, so an unrelated later turn cannot finish the assignment. A disconnected receiver must return through a fresh verified turn before continuing.

A precise assignment might ask: “Investigate API storage and responses for the saved filter. Determine whether saving persists the selected value and returns it. Return observations and source locations.” It should also state any authorized write scope. The original agent continues its reload investigation and integrates the evidence against the original acceptance conditions.

## Delivery, reading, and success are different events

| Observation | What it establishes |
| --- | --- |
| `queued` | The send was durably admitted. |
| Native submission | The selected transport accepted a notification. |
| Full message read | The authenticated participant retrieved the body. |
| Acknowledgement | The recipient acknowledged an already-read message. |
| Assignment accepted / `started` | The bound native turn accepted execution. |
| Lifecycle/result report | The executor or provider supervisor reported a particular outcome. |
| Original task resolved | The owner recorded an outcome against the original task and its evidence. |

Discovery, sending, and `delivery_status` include `delivery` and `delivery_note`. `push` means a registered notification endpoint is available; it is not proof of receipt. `pull-only` means no usable endpoint is registered, so the message waits for the recipient's next native turn. A missing or invalid socket is classified as `pull-only`. An app bridge can still be used through the host-owned forwarding route when available.

Use `collaboration_inbox` to find pending messages and `collaboration_message(message_id)` to read a complete body. A notification preview is insufficient for acknowledgement. `collaboration_ack` accepts either one `message_id` or up to 100 `message_ids`; every item must belong to the recipient and have full read evidence. One invalid item rejects the entire batch. Re-acknowledging an already-read duplicate is allowed.

`collaboration_reply(message_id, message, key)` replies and acknowledges atomically. `collaboration_forward` prepares a native notification route; it does not send the notification itself. Execute the returned tool through its owning host, then call `collaboration_submitted` only after that native tool reports successful submission. A sender's submission report remains distinct from the receiver's acknowledgement.

For ordinary peer assignments, `collaboration_report` allows `started`, `waiting`, `error`, `failed`, `cancelled`, and `completed` from the bound executor. Independent provider sessions have lifecycle and final responses forwarded by their supervisor. They do not need to imitate the supervisor with duplicate reports; explicit peer messages still use send/reply when requested. `collaboration_task` is a diagnostic read after an event or problem, not a polling loop.

## Publish discoveries that more than one peer may need

The **Newsroom** is a shared, attributed discussion of findings. For the filter investigation, an agent might publish “Reload skips saved filter” with the relevant source and test evidence in the body. Currently active native peers receive only the title, article identifier, and revision. They choose whether the body is relevant and call `newsroom_read` to retrieve it.

`newsroom_publish` takes a title of at most 30 Unicode characters, a bounded body, and a stable key. The named tool caps body text at 16,000 characters and the storage layer additionally enforces a 32,768-byte limit. `newsroom_revise` preserves correction history, while `newsroom_comment` adds attributed discussion to the specified revision. `newsroom_read(history=true, after=..., limit=...)` explicitly pages history and comments; the default body read does not expand them. `newsroom_seen` marks the delivered event as seen.

Headlines are delivered at eligible hooks to active peers without subscription. The mechanism does not wake inactive sessions or replay the backlog from an inactive period. It also does not insert article bodies into ordinary shared memory. Publishing, reading, commenting, and subscribing are knowledge-sharing actions; each remains separate from a user's authorization or task completion.

## Recover the original conversation

An uncertain transport outcome keeps the original message identity and sender/recipient binding. Unacknowledged messages are retained across delivery budgets, TTL, and connection closure unless explicitly cancelled. Service recovery can redeliver an uncertain message; stale generations must not undo a newer acknowledgement or owner.

Use `delivery_status` for an observed delivery problem. After a real repair, `delivery_redrive` needs the exact message ID, current revision, repair reference, and stable key. It retries the same message. It cannot rebind a message to an arbitrary recipient or revive a cancelled message. A closed or expired participation binding needs valid native reconnection; inventing an address or ownership record is not recovery.

For native children, `delegation_prepare` records one immediate spawn intent and can bind an exact task revision. The subsequent native spawn must prove a direct parent relationship; copied parent references and nested spawning do not establish supported lineage. Preparation alone is not execution. Independent roots instead follow [provider planning and execution](provider-transports.md). A received peer report also does not confer independent evaluator authority: an explicit review requires the correct role, exact candidate, and authenticated consumption.

## Implementation and regression references

Communication state lives in [src/neurath/agents/store.py](../../../src/neurath/agents/store.py), `lifecycle.py`, `delivery.py`, `delivery_recovery.py`, and `newsroom.py`; named inputs are defined in [src/neurath/runtime/task_schema.py](../../../src/neurath/runtime/task_schema.py) and `communication_schema.py`. Focused coverage includes [tests/test_agent_delivery.py](../../../tests/test_agent_delivery.py), [tests/test_newsroom.py](../../../tests/test_newsroom.py), [tests/test_provider_reply_route.py](../../../tests/test_provider_reply_route.py), and [tests/runtime/agent_harness/test_delegation_evidence.py](../../../tests/runtime/agent_harness/test_delegation_evidence.py). Delivery tests cover body-read ACK checks, restarts, old generations, and resumed native turns; Newsroom tests cover title-only delivery, corrections, and inactive periods.
## Named input reference

The tables below are the current named-tool input contract. Nested required fields are required when their parent object or array item is supplied. Schema acceptance is only the first check; native identity, ownership, source, revision, and operation-specific prerequisites still apply. The host supplies `_neurath_binding`; do not synthesize it.

Every response has `ok` and `operation`. A successful call carries its canonical `result`; a failure carries `error.code`, `error.message`, `error.state`, `error.retryable`, and `error.next_action`. An `ok` envelope establishes the stated operation only, not the user goal. Preserve returned IDs and revisions for dependent calls.

### `collaboration_register`

| Field | Presence / default | Type and limits |
| --- | --- | --- |
| `name` | required | text; 1–256 characters |
| `summary` | optional; default `""` | text; 0–4096 characters |

### `collaboration_discover`

| Field | Presence / default | Type and limits |
| --- | --- | --- |
| `query` | optional; default `""` | text; 0–16000 characters |
| `limit` | optional; default `20` | integer; 1–100 |

### `collaboration_inbox`

| Field | Presence / default | Type and limits |
| --- | --- | --- |
| `limit` | optional; default `20` | integer; 1–100 |
| `conversation` | optional; default `""` | text; 0–512 characters |
| `include_read` | optional; default `false` | boolean |

### `collaboration_send`

| Field | Presence / default | Type and limits |
| --- | --- | --- |
| `to` | optional; default `""` | text; 0–512 characters |
| `message` | optional; default `""` | text; 0–16000 characters |
| `key` | optional; default `""` | text; 0–512 characters |
| `kind` | optional; default `"question"` | text: `"question"`, `"proposal"`, `"update"`, `"result"` |
| `messages` | optional; default `[]` | array; 0–32 items |
| `messages[].to` | required | array; 1–32 items; text; 1–512 characters; distinct |
| `messages[].message` | required | text; 1–32768 characters |
| `messages[].key` | required | text; 1–512 characters |
| `messages[].kind` | optional | text: `"question"`, `"proposal"`, `"update"`, `"result"` |

### `collaboration_message`

| Field | Presence / default | Type and limits |
| --- | --- | --- |
| `message_id` | required | text; 1–512 characters |

### `collaboration_ack`

| Field | Presence / default | Type and limits |
| --- | --- | --- |
| `message_id` | optional; default `""` | text; 0–512 characters |
| `message_ids` | optional; default `[]` | array; 0–100 items; text; 1–512 characters |

### `collaboration_reply`

| Field | Presence / default | Type and limits |
| --- | --- | --- |
| `message_id` | required | text; 1–512 characters |
| `message` | required | text; 1–16000 characters |
| `key` | required | text; 1–512 characters |

### `collaboration_assign`

| Field | Presence / default | Type and limits |
| --- | --- | --- |
| `to` | required | text; 1–512 characters |
| `message` | required | text; 1–16000 characters |
| `key` | required | text; 1–512 characters |

### `collaboration_accept`

| Field | Presence / default | Type and limits |
| --- | --- | --- |
| `task_id` | required | text; 1–128 characters |

### `collaboration_report`

| Field | Presence / default | Type and limits |
| --- | --- | --- |
| `task_id` | required | text; 1–128 characters |
| `state` | required | text: `"started"`, `"waiting"`, `"error"`, `"failed"`, `"cancelled"`, `"completed"` |
| `key` | required | text; 1–512 characters |
| `detail` | optional; default `""` | text; 0–16000 characters |

### `collaboration_task`

| Field | Presence / default | Type and limits |
| --- | --- | --- |
| `task_id` | required | text; 1–128 characters |

### `collaboration_forward`

| Field | Presence / default | Type and limits |
| --- | --- | --- |
| `message_id` | required | text; 1–512 characters |

### `collaboration_submitted`

| Field | Presence / default | Type and limits |
| --- | --- | --- |
| `message_id` | required | text; 1–512 characters |
| `transport` | required | text; 1–100 characters |

### `collaboration_conversation`

| Field | Presence / default | Type and limits |
| --- | --- | --- |
| `conversation` | required | text; 1–512 characters |

### `collaboration_close`

| Field | Presence / default | Type and limits |
| --- | --- | --- |
| `conversation` | required | text; 1–512 characters |

### `collaboration_subscribe`

| Field | Presence / default | Type and limits |
| --- | --- | --- |
| `to` | required | text; 1–512 characters |

### `collaboration_unsubscribe`

| Field | Presence / default | Type and limits |
| --- | --- | --- |
| `to` | required | text; 1–512 characters |

### `collaboration_publish`

| Field | Presence / default | Type and limits |
| --- | --- | --- |
| `message` | required | text; 1–16000 characters |
| `key` | required | text; 1–512 characters |

### `newsroom_headlines`

| Field | Presence / default | Type and limits |
| --- | --- | --- |
| `limit` | optional; default `20` | integer; 1–100 |

### `newsroom_read`

| Field | Presence / default | Type and limits |
| --- | --- | --- |
| `article_id` | required | text; 1–512 characters |
| `history` | optional; default `false` | boolean |
| `after` | optional; default `0` | integer; 0–2147483647 |
| `limit` | optional; default `10` | integer; 1–100 |

### `newsroom_publish`

| Field | Presence / default | Type and limits |
| --- | --- | --- |
| `title` | required | text; 1–30 characters |
| `body` | required | text; 1–16000 characters |
| `key` | required | text; 1–512 characters |

### `newsroom_revise`

| Field | Presence / default | Type and limits |
| --- | --- | --- |
| `article_id` | required | text; 1–512 characters |
| `revision` | required | integer; 1–9007199254740991 |
| `title` | required | text; 1–30 characters |
| `body` | required | text; 1–16000 characters |
| `key` | required | text; 1–512 characters |

### `newsroom_comment`

| Field | Presence / default | Type and limits |
| --- | --- | --- |
| `article_id` | required | text; 1–512 characters |
| `revision` | required | integer; 1–9007199254740991 |
| `body` | required | text; 1–16000 characters |
| `key` | required | text; 1–512 characters |

### `newsroom_peers`

| Field | Presence / default | Type and limits |
| --- | --- | --- |
| `limit` | optional; default `20` | integer; 1–100 |

### `newsroom_seen`

| Field | Presence / default | Type and limits |
| --- | --- | --- |
| `event_id` | required | text; 1–512 characters |

### `delivery_status`

| Field | Presence / default | Type and limits |
| --- | --- | --- |
| `message_id` | required | text; 1–64 characters |

### `delivery_redrive`

| Field | Presence / default | Type and limits |
| --- | --- | --- |
| `message_id` | required | text; 1–64 characters |
| `expected_revision` | required | integer; 1–9007199254740991 |
| `repair_reference` | required | text; 1–1024 characters |
| `key` | required | text; 1–512 characters |

## Parallel waves and collaboration choice

Native subagents are the default for work owned by the current conversation, including large tickets. Duration and separate worktrees are execution properties, not reasons to create a user-facing conversation. Select a user session only when the user is expected to visit it and continue the work. A different provider may be selected autonomously when capable reasoning from another perspective can expose alternatives, repeated assumptions or missed counterexamples. The owning orchestrator collects the result; a technical provider worker does not imply a new user-managed app task. Host tools retain their own explicit-creation requirements.

`provider_route` and `provider_run` accept `purpose` (`task`, `perspective`, `user-session`) and `reason`. The default `task` route points to native delegation; direct provider execution rejects that default. `perspective` requires a different provider and a concrete rationale. `user-session` requires a reason describing expected user continuation. These choices do not replace model planning, permission inheritance or native readiness checks.

The root owns each ticket workflow, integration and review. It dispatches implementation and review as separate direct children; implementation children do not spawn reviewers. Workers without verified write authority return patch artifacts for the root to integrate under its claim.

`delegation_wave_prepare` binds a DAG to an exact in-progress task revision. Inputs are `wave_id`, `task_id`, `expected_task_revision`, `entries` (each with `delegation_id` and `depends_on`), `max_parallel`, `capacity_basis`, optional `serialization_reason`, and a stable `key`. Capacity is an owner observation, not host-attested merely because a number was supplied. Cycles and missing dependencies are rejected. If independent work is restricted to one slot, a serialization reason is required.

Prepare and spawn each ready entry before waiting. The native hook counts in-flight spawn reservations and actual dispatches; it rejects waiting while ready work has a free slot. Claude parallel Agent dispatch uses background execution. Successful consumed results unlock dependents; failed or merely reported results do not. After an event, `delegation_wave_read(wave_id)` gives the current projection. `delegation_wave_retry(wave_id, delegation_id, replacement_id, key)` replaces only an observed failed attempt, preserving its history. A task cannot report success while its wave remains unfinished or unsuccessful. These records describe execution under the existing task ledger; they are not a second goal list.

## Independent review context

Prepare reviewers with `delegation_prepare(role="review")` and create a fresh native child. Codex must explicitly use `fork_turns="none"`; a new Claude Agent must not resume an existing child. The native spawn journal binds these observed options to the actual child. Ordinary inherited-context children remain usable for non-review work. An implementation child cannot be reused as the reviewer.

Review admission, result consumption, prior-review reuse and publication read the same context proof in addition to lineage, exact head and artifact digests. Missing or inherited context is rejected. A reviewer-provided flag is insufficient. Provide the exact diff, requirements, acceptance conditions and source evidence; avoid supplying the implementation conclusion as the expected verdict.

Legacy phase workflows also supply `workflow_id` when preparing the wave and submit `native_wave_receipt: wave_id=...` at completion. The phase gate reads the actual wave bound to that exact workflow.

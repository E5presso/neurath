<!-- date: 2026-09-13; synced_from: 655c8768709e59b5e5012bab0adc4d888e3e7fa5 + current working-tree facts -->

[한국어](../../ko/contributing/collaboration-contract.md)

# Deliver work without losing who said what

A collaboration message is a durable, attributed envelope addressed to a logical recipient. The delivery contract preserves its identity and content across transport retries, while task acceptance and task effects remain separately observable. It assumes intact durable storage and an eventually available, authorized receiver. Until those conditions hold, pending delivery or a repair requirement is the accurate result.

## Persist first, notify second

The envelope retains `message_id`, sender, logical recipient, kind, conversation, payload and digest, creation time, and optional task or reply linkage. The store commits before returning success or notifying a transport. A caller's stable key remains visible to the recipient even when the immediate notice includes only a lookup ID.

Use `collaboration_register` to announce the authenticated participant and `collaboration_discover` to find an exact address. Never substitute a guessed native UUID, PID, actor, or socket for a discovered logical recipient. Shared state belongs to the Git-common project runtime database; separate clones do not automatically share a mailbox.

`collaboration_send` accepts either the single-message fields `to`, `message`, `key`, `kind`, or a `messages` array. Do not mix the forms. Each batch entry has a nonempty recipient array, message, and key; a batch commits atomically to its exact recipients. The same key and same content deduplicate; changed content under that key conflicts. For example, after replacing the illustrative address with an actual discovered address:

```json
{
  "messages":[
    {
      "to":["DISCOVERED_PEER_ADDRESS"],
      "message":"Please check whether the documented response matches the current API test. Read-only analysis only.",
      "key":"response-contract-question-1",
      "kind":"question"
    }
  ]
}
```

The single form accepts up to 16,000 characters of message text. A batch allows up to 32 entries, up to 32 unique recipients per entry, and up to 32,768 characters per entry. These structural limits do not authorize a wider audience or new work.

## Read the body before acknowledging

| State | Established fact | Still unestablished |
| --- | --- | --- |
| `queued` | Envelope stored durably | Transport acceptance |
| `submitted` | Host transport accepted the input | Recipient read or ACK |
| `received` | Intended recipient acknowledged receipt | Work acceptance or effects |
| `replied` | Recipient response stored | Issuer acceptance of the task result |

The recipient uses `collaboration_inbox` and `collaboration_message` to read the complete body. `collaboration_ack` can take one `message_id` or a `message_ids` array for bodies already read. An ID-only notice or failed body lookup is insufficient. `collaboration_reply` takes `message_id`, `message`, and `key`; it records ACK and response atomically.

ACK is authenticated as the intended recipient, durable, and idempotent. An already-read duplicate can be acknowledged again. ACK stops delivery retries; it does not accept a task or certify an external effect. The contract tolerates duplicate transport delivery and ACK. Exactly-once external effects are not guaranteed, so effectful task code must handle its own deduplication where required.

Ordinary peer work uses `collaboration_assign` → `collaboration_accept` → `collaboration_report`. Report states are `started`, `waiting`, `error`, `failed`, `cancelled`, and `completed`. The issuer reads the result and retains follow-up responsibility until accepted completion, cancellation, or verified handoff. A peer request is subordinate to the real user's authority. An ordinary peer report does not become an independent evaluator result for an explicit phase contract.

## Retry the same envelope

Owned transports redeliver the same ID, key, recipient, and body. Per-attempt deadlines and backoff control frequency; they do not expire an ordinary task or exhaust its durable chances. Database changes, native readiness, reconnection, and per-message deadlines drive attempts. Approval and input waits need the relevant readiness event. Unavailable endpoints back off instead of spinning or polling task status.

A sending, uncertain, failed, or unacknowledged submitted attempt remains eligible for supported retry. Receiver process absence or a lost ACK is not by itself a dead-letter condition. A receiver endpoint generation and ACK fence late old-attempt results, while leases prevent identity takeover. A new native session UUID does not automatically inherit another mailbox.

When `collaboration_forward` returns an exact supported host tool and arguments, execute that route and call `collaboration_submitted` only after actual tool success. A route proposal is not submission. If no supported immediate bridge exists, the message stays queued for a supported hook or resume. Reading shared history cannot create a Desktop wakeup bridge.

`collaboration_conversation` reads conversation state. The ordinary default budget is 32 messages over 24 hours; this can limit new activity without deleting accepted pending messages. `collaboration_close` retains pending obligations or records explicit authorized cancellation. Closing does not transfer ownership. Durable subscriptions use `collaboration_subscribe`, `collaboration_publish`, and `collaboration_unsubscribe`.

## Diagnose a held delivery

`delivery_status` requires `message_id` and returns current delivery state, recent attempts, and any repair hold. A dead-letter hold retains the body, failure history, and repair requirement. Current classifications include envelope-version and recipient-binding problems.

After repairing the actual cause, the authenticated owner calls `delivery_redrive` with the same `message_id`, the returned `expected_revision`, `repair_reference`, and a stable `key`. The reference documents the repair; it does not prove that the transport is now valid. The real route revalidates while preserving the original recipient and content. Redrive cannot widen permissions, revive cancelled work, or rebind a recipient by editing private database rows.

| Interruption | Required retained information | Recovery observation |
| --- | --- | --- |
| Receiver dies before send | Original envelope and key | Delivery resumes to the authorized restored receiver |
| Receiver dies after input, before ACK | Same body and attempt history | Duplicate body can be read and ACKed |
| Transport or ACK response is lost | Uncertain or unACKed attempt | Supported retry converges without inventing receipt |
| Old attempt completes after endpoint changes | Generation and current ACK | Late result cannot undo the new state |
| Conversation expires or closes with pending input | Accepted obligations | Pending or explicit cancellation remains visible |
| Repair hold is released | Revision, repair reference, original envelope | Actual transport validation determines progress |

## Share findings with active peers

The newsroom distributes concise findings without copying entire conversations. `newsroom_publish` takes `title` (1–30 characters), `body` (1–16,000 characters), and `key`. Normal host events expose a title and lookup ID; interested peers read the body with `newsroom_read`. `newsroom_headlines` and `newsroom_peers` support discovery, and `newsroom_seen` records observation.

Corrections use `newsroom_revise` with `article_id`, current `revision`, `title`, `body`, and `key`; comments use `newsroom_comment` with the same identity and revision plus body and key. Attribution and revisions are retained. Currently active attested sessions and children participate; activity expires after 10 minutes. Hook notices are bounded to 3,000 bytes, and publish/revise/comment operations are limited to 20 per author per minute.

Idle, paused, and ended peers are not woken. Notices missed while inactive are not replayed. Article bodies are not automatically copied into memory, a parent conversation, or upstream reporting. An article is a report with attribution, not an approved specification or certified result.

## Implementation and acceptance

[Agent storage](../../../src/neurath/agents/store.py), [delivery](../../../src/neurath/agents/delivery.py), [recovery](../../../src/neurath/agents/delivery_recovery.py), and [newsroom](../../../src/neurath/agents/newsroom.py) own these behaviors. [Communication tests](../../../tests/test_communication_mcp.py), [delivery-recovery tests](../../../tests/test_delivery_recovery.py), and [newsroom tests](../../../tests/test_newsroom_mcp.py) cover schema and fixture behavior.

Native acceptance additionally needs all four Codex/Claude directions, idle issuer delivery through the owned connection, death before and after send, lost ACK, stale generations, retained pending messages, repair redrive, and a long-running task that still receives messages and cancellation. This is an acceptance matrix, not a claim that every current host combination has been freshly certified. See [provider transports](provider-transports.md) for connection ownership and [agents](agents-reference.md) for identity.

# Provider collaboration contract

**English** · [한국어](../../ko/contributing/collaboration-contract.md)

[Architecture](architecture.md) · [Transport implementation](provider-transports.md)

Status: accepted product contract; implementation migration and actual-host acceptance remain open.
This document defines the required behavior. Existing code and passing legacy tests do not
establish that these requirements are implemented. Model selection and the agent-facing MCP
surface are specified in [Model planning and MCP operation](model-planning-mcp.md).

## Goal and decisions

Sessions, native subagents and provider runtimes collaborate without the user relaying messages,
executing commands or repeatedly granting permissions already assigned to the work. Either
Codex or Claude can be the initial root. Approved work continues while its execution process
is alive, whether or not the user is watching.

| ID | Accepted decision | Consequence |
| --- | --- | --- |
| D01 | The initial root is provider-neutral | Cover Codex→Codex, Codex→Claude, Claude→Codex and Claude→Claude |
| D02 | New execution inherits the creator's effective permission policy | Inspect actual settings, translate their meaning and verify application before assignment |
| D03 | User observation is outside the harness lifecycle | No app membership, dashboard, remote-view connection or human presence gate |
| D04 | A provider instance owns its native sessions and subagents | Native internal communication stays provider-owned; Neurath handles communication between instances |
| D05 | Delivery is at-least-once; omission is worse than duplication | Retain unacknowledged accepted messages and resend with the same key |
| D06 | LLM recipients can recognize duplicate keys | Supply stable identity and unchanged content; do not promise exactly-once task effects |
| D07 | Collaboration is driven by events | No completion polling, heartbeat automation or separate LLM receiver session |
| D08 | Task lifetime is not an RPC timeout | Bound individual transport operations without killing ordinary work for elapsed time |

These decisions supersede prior requirements for saved Desktop project affiliation and remote
opening, and the earlier prohibition on retransmitting uncertain delivery attempts. They do
not remove native identity, explicit deny rules, host hooks, worktree ownership or publication
authorization. Model difficulty must not change permission scope.

## Domain and ownership

| Term | Meaning |
| --- | --- |
| Provider kind | Codex or Claude; a product name, not a process identity |
| Provider instance | A durable owned execution identity whose runtime connections and native process generations can be replaced during recovery |
| Logical recipient | A durable addressed participant within a project and owned provider execution |
| Native session | The provider's session identifier; its binding is verified, not supplied as caller authority |
| Native subagent | A provider-attested child governed by that provider's supported topology |
| Issuer | The participant responsible for receiving and acting on assigned-work reports |
| Message | An immutable addressed payload with a stable key and durable identity |
| Attempt | One transport submission of a message; attempts may be duplicated |
| Receipt ACK | The addressed recipient acknowledges receipt; this is not task completion |
| DLQ | Durable isolation of an accepted message requiring a specific repair before delivery can proceed |

Two processes using the same provider kind are not automatically one instance. Do not build
an independent offline-node model for every native child. A provider's internal task failure
is still reported; native operations may fail even while its process is alive.

The issuer owns follow-up until the work is accepted, explicitly cancelled or handed over
through a verified transfer. Its current model turn ending is not an implicit handover.
Observing a subprocess exit or native connection EOF does not authorize another actor to
take its worktree claim or impersonate its session.

## Permission inheritance

**FR-P01.** Capture the creator's current effective policy from the admitted native invocation.
Do not use a stale global default, prompt phrase or unverified model report as that policy.
The inherited envelope covers approval behavior, tool restrictions, filesystem/network
confinement and relevant provider-specific settings. Every field carries its observation
source; an unavailable field remains unobserved.

**FR-P02.** For the same provider, preserve the effective native settings. For a different
provider, map capabilities and restrictions separately; mode names alone are not equivalence.
Apply workspace-relative permissions to the assigned workspace and only the necessary shared
harness state. Do not grant write access to another owner's source checkout as a side effect.

| Source behavior | Mapping requirement |
| --- | --- |
| Unattended broad tool approval | Claude `bypassPermissions` is a supported candidate; Codex approval and sandbox settings are separate inputs |
| Refuse operations requiring a new approval | Preserve this behavior; Claude `dontAsk` must not silently become `bypassPermissions` |
| Read-only or planning | Preserve allowed read operations and actual write restrictions; `plan` alone is not proof of OS confinement |
| Interactive approval, automatic edit approval or classified approval | Preserve the decision boundary through supported native settings; do not guess a universal mode alias |
| Explicit tool deny or filesystem/network restriction | Preserve it independently of the approval mode |

The adapter owns a versioned mapping and its tests. If the destination cannot express or
verify the source envelope, report the exact unsupported dimensions and withhold assignment.
Do not silently widen or narrow permissions and call the inheritance successful.

**FR-P03.** Propagate from the immediate creator. A restricted intermediate session passes
its restrictions to its children; the initial root's broader settings are not restored.
Only an explicit authorized policy change overrides inheritance. Preserve deny rules and
hooks, including when a broad approval mode skips a provider approval callback.

**FR-P04.** Complete installation, native activation, actual policy readback, normal ownership
and named-task availability before dispatching implementation. Preparation is distinct from
assignment. A newly created workspace is not assumed to contain ignored installation files.
The issuer arranges missing prerequisites through supported installation and lifecycle paths.
No user command execution, global permission rewrite or foreign live resume is a repair path.

## Runtime lifetime and supervision

**FR-L01.** Observe process and native connection events on the execution host. User presence,
app UI state and remote observation connections do not affect execution or delivery.
An idle model turn, input/approval wait, process failure and explicit cancellation are distinct.

**FR-L02.** Durable acceptance returns before model execution finishes. Report acceptance,
observed start, waiting, error, disconnect, cancellation and completion separately. A successful
native turn is not proof of task effects. The issuer reads the report body and owns its response.

**FR-L03.** Keep an owned provider connection available after a turn ends while issued work
or unacknowledged required reports remain. An incoming event resumes the same logical issuer
through its supported owning connection. Do not create another LLM session merely to receive
reports, and do not resume a live session from a competing provider connection.

**FR-L04.** If an issuer instance dies while another instance is still executing authorized
work, do not cancel that work solely because its issuer is unavailable. Persist its reports
for later receipt. This does not promise continued execution on a powered-off host or recovery
of a lost disk. Preserve interrupted execution separately from message delivery recovery.

## Message identity and delivery

**FR-M01.** Validate sender, recipient and payload before acceptance. Atomically commit the
immutable message before returning durable acceptance or attempting transport notification.
The public result distinguishes stored/accepted, transport-submitted and recipient-acknowledged.

**FR-M02.** The envelope includes `message_id`, sender, logical recipient, kind, conversation,
payload reference/content digest, creation time and optional task/reply linkage. Bind the
publisher's idempotency key to the exact immutable request. Reusing the key with different
content is a conflict. Every retry carries the same message identity and content; a new
attempt may have a different attempt identifier, never a new logical message key.

**FR-M03.** Expose the stable key to the receiving LLM. A small notification may carry the key
and a named body-lookup operation instead of copying the full body. Repeated notifications
must remain recognizable as the same message. The LLM may ignore duplicate work and ACK again;
the harness does not guarantee exactly-once execution of external effects.

**FR-M04.** An accepted valid message remains eligible until recipient ACK or explicit recorded
cancellation. Retry when delivery or ACK is uncertain, including recovery from `sending`,
`uncertain`, `failed` and unacknowledged `submitted`. None is a permanent no-retry marker.
Transport success and a process restart do not synthesize an ACK.

**FR-M05.** Retry through the active owning transport, with bounded per-request timeouts and
backoff between attempts. Retry scheduling concerns identified outstanding messages, not
periodic inbox/task/process-status polling. Reconnection, native readiness changes and
per-message delivery/ACK deadlines may trigger attempts. Do not spin during approval waits
or keep a dead process alive; preserve the pending message for a later eligible connection.
Backoff caps frequency, not the lifetime of the task or the number of durable recovery chances.

**FR-M06.** A recipient ACK must be authenticated as the addressed participant and stored
durably. ACK requires receipt of the full body, either inline or through a successful body lookup;
an ID-only notification is insufficient. Failed body lookup leaves delivery pending. A recipient
that already received that immutable message may ACK a duplicate again. A duplicate ACK is harmless.
ACK stops delivery retries; task acceptance, rejection,
completion and follow-up remain separate task messages. A late attempt result cannot overwrite
an ACK or an attempt from a newer owned connection generation.

**FR-M07.** Ordinary conversation TTLs and message budgets may limit new conversation activity,
but must not make an already accepted unacknowledged message disappear from recovery. Closing
a conversation with pending messages must return a visible pending result or an explicit
authorized cancellation record. No silent discard on expiry, close, restart or cleanup.
This requirement concerns collaboration messages, not Newsroom's intentionally transient feed.

The delivery guarantee assumes intact durable storage and an eventually available authorized
recipient. While those prerequisites are absent, report pending or repair-required; do not
claim delivery. Explicit cancellation is a visible terminal exception, not successful receipt.

## Recovery and DLQ

**FR-R01.** Persist logical recipient identity separately from PID, socket path and native
connection generation. On recovery, prove the owned execution and its prior recipient binding,
restore the supported native session and verify current policy/activation before delivery.
A new native UUID is not an automatic mailbox successor. A live lease prevents competing
owners; recovery must never steal an active lease or accept an arbitrary caller identity.

**FR-R02.** After an eligible owner reconnects, replay outstanding messages with their original
keys. A submitted-before-crash message may be delivered twice. Preserve both attempts and the
eventual ACK. If the native provider cannot restore the addressed execution, retain its mailbox
and report the capability gap; do not invent a replacement conversation or accept work for it.

**FR-R03.** Temporary process absence, lost responses and ACK loss remain retryable. A DLQ is
for an accepted message whose repair prerequisite is known, such as an incompatible envelope
version or invalidated recipient binding. It retains the message, failure classification,
attempt history and required repair. It is neither a deletion queue nor a timer-based expiry.
An unresolved DLQ item prevents a claim that all messages were delivered.

**FR-R04.** Redrive is an authenticated named operation by the authorized owner after the repair.
It preserves message identity/content and records the transition. Do not replay a permission
denial by expanding rights, revive explicitly cancelled work, or clear ambiguity through direct
database edits. Publication idempotency and delivery retries are distinct contracts.

## Acceptance scenarios

| ID | Scenario and required observation | Requirements |
| --- | --- | --- |
| AC01 | All four provider directions inherit observed policy; a restricted intermediate creator remains restricted | FR-P01–P03 |
| AC02 | Broad Claude approval works through the official SDK; explicit deny and hooks still apply; unsupported cross-provider confinement blocks before assignment | FR-P01–P04 |
| AC03 | Missing installation, activation, claim or named tools produces a precise preparation result without assigning work | FR-P04 |
| AC04 | Ending an issuer turn leaves its owned connection ready; a later child report starts a follow-up in the same logical issuer, body lookup/ACK and response occur | FR-L02–L03 |
| AC05 | Kill the receiver before delivery; an independently running sender completes its approved work; recovery delivers the original queued key | FR-L01,L04,M01,R01–R02 |
| AC06 | Kill the receiver after delivery but before ACK; replay uses the same key and content, duplicate delivery is permitted, no message is omitted | FR-M02–M06,R02 |
| AC07 | Drop the transport response or ACK; every non-ACK state remains recoverable and eventually reaches ACK when the receiver is available | FR-M04–M06 |
| AC08 | A stale attempt finishes after a new owner/ACK; it cannot undo the new state or take ownership | FR-M06,R01 |
| AC09 | Advance ordinary TTL, exhaust a conversation budget and request close while a message is pending; the message remains recoverable or explicitly cancelled | FR-M07 |
| AC10 | A repair-required message enters DLQ with its body and reason; authorized redrive preserves its key; arbitrary rebinding and revival of cancellation fail | FR-R03–R04 |
| AC11 | An execution longer than an RPC timeout continues; message and cancellation events remain usable without status polling or a receiver LLM | FR-L02–L03,M05 |
| AC12 | Body lookup fails after an ID-only notification: no ACK is recorded and the message is redelivered; a previously read duplicate can be ACKed again | FR-M06 |

Deterministic queue/transport tests prove transitions. Actual installed Codex and Claude runs
must additionally demonstrate AC01–AC06 and AC11 using normal named task entry points and
provider-owned connections. Do not substitute direct calls to internal worker functions,
fabricated native identities, metadata-only app checks or summed historical test counts.
Retain raw local evidence privately and identify which scenarios each run actually covers.

## Implementation ownership and migration

| Work package | Code owners / focused tests | Depends on |
| --- | --- | --- |
| W1 Permission envelope and mapping | `providers/contracts.py`, provider adapters, `readiness.py`; provider policy tests | Accepted contract; model/MCP shared input agreement |
| W2 Durable retry transitions and retention | `agents/store.py`, `agents/delivery.py`; delivery and lifecycle tests | FR-M envelope/ACK contract |
| W3 Owned reconnection and native delivery | `providers/jobs.py`, `supervision.py`, `codex_delivery.py`, `execution_claude.py`; provider recovery tests | W1, W2 |
| W4 Named preparation/recovery operations | `runtime/task_schema.py`, `runtime/tasks.py`, host bindings, installation projections | W1, W2; model/MCP contract |
| W5 Integrated actual-host acceptance and docs | Bilingual guides, final fixtures, package/install validation | W1–W4 |

W1 and W2 may proceed independently in isolated scopes. W3 and W4 must agree on shared schemas
before concurrent edits. One integrating owner applies changes to shared runtime schemas,
CLI compatibility, installer policy and documentation entry points. The parallel model/MCP
owner supplies reviewed contracts or isolated patches. No concurrent claim or state-file edits
are a substitute for this agreement.

Migration starts from failing tests for the changed semantics. Remove the app-access prerequisite
from ordinary provider execution and remove no-retry assertions for ambiguous messages; replace
them with omission/recovery assertions. Retain explicit ownership, permission and cancellation
tests. Do not remove old checks merely to obtain a pass. This contract does not itself migrate
the currently installed harness, select a model, publish issues, commit, push or release.

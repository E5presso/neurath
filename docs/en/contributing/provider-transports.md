# Provider sessions and native transports

**English** · [한국어](../../ko/contributing/provider-transports.md)

[Contributing](index.md) · [Agent collaboration](agents-reference.md) · [Task tools](task-tools.md)

The [collaboration contract](collaboration-contract.md) defines provider-neutral permission
inheritance, process lifetime and at-least-once delivery. [Model planning](model-planning-mcp.md)
defines selection before new work. This reference describes the current source implementation;
installed-host acceptance must be checked separately from source and schema tests.

## Execution routes

A provider selects the model service; a transport owns the connection used to create, message
and stop native execution. Either Codex or Claude may be the initial root. Sessions and native
subagents within one provider instance use its supported internal communication. Neurath owns
messages between instances. App project membership, remote viewing and user presence are not
execution prerequisites or completion criteria.

| Route | Current implementation | Boundary |
| --- | --- | --- |
| Codex app-server | Owned create/read/start/steer/interrupt and recorded-session restoration | Worker-owned JSON-RPC connection; no attachment to another live client |
| Claude Agent SDK | Owned async client, streamed responses, serial queries, interrupt and recorded-session restoration | Requested options, native mode and actual readiness are separate observations |
| Existing app/native peer tools | Discover and use the exact tool/recipient returned by the host | Optional routes; a route proposal is not delivery or permission inheritance |
| Bounded CLI compatibility | Short read-only legacy execution and its own status/cancel/continuation | Not the ordinary session execution path or an agent-facing MCP replacement |
| Claude Desktop/Cowork | No external lifecycle adapter | UI availability does not establish a callable native execution connection |

The Codex adapter validates a native project ID when explicitly supplied and checks it in the
creation result. An omitted ID does not require a saved project. An optional app
preparation route may use an app project ID, but its metadata cannot attest native policy or
make app membership a prerequisite for ordinary provider work. Do not edit app databases,
fabricate identity, or resume a live session from a competing connection.

## Model planning and inherited permissions

Use `provider_models`, `provider_plan` and `provider_plan_read` to inspect observations and retain
the selection plan. `provider_run` consumes the plan ID/revision, assignment revision, exact
model or planned inheritance, reasoning setting and stable execution key. The dispatcher
compares the plan with the current assignment, policy and inventory before durable admission;
it compares the actual model before substantive assignment. A changed model needs a new plan
revision, not a hidden fallback. Requested, prepared, observed and accepted are distinct states.

Model inventory has provider-specific limits. Codex uses its native adapter; Claude uses a short
official SDK metadata handshake with existing settings and without querying a model. The worker
removes parent identity environment fields. A catalog response does not prove authentication,
inference or a configured default. Native maintenance choices use the separate exact-question
and user-response binding described in [Task tools](task-tools.md).

`provider_run` defaults to `mode="inherit"`. With a worktree and assignment but no explicit
requested policy, `provider_route` proposes that inheritance path. The current native policy of
the immediate creator is the source, including when the root is Claude. An explicit mode or
policy field is checked against inheritance; it does not silently widen permissions.

Codex approval policy, reviewer, collaboration mode and native sandbox fields remain separate.
Same-provider requests retain the observed policy. The current cross-provider mapping supports
broad unattended approval (`never` with `danger-full-access` and a non-Plan collaboration mode,
or Claude `bypassPermissions`) when known restrictions can be preserved. Other cross-provider
combinations return specific unsupported dimensions rather than guessed mode aliases.

Claude accepts `plan`, `dontAsk`, `default`, `acceptEdits`, `auto` and `bypassPermissions`.
`dontAsk` does not grant a previously disallowed tool. Broad approval does not remove explicit
deny rules, hooks or worktree ownership. Do not mix Codex policy fields into a Claude request.
Plan/read-only observations do not authorize implementation.

Native modes, configured settings candidates and verified loaded configuration are distinguished.
Candidate files are not proof of in-memory overrides. Precise native observations take precedence
when available; known rules, hook differences and configured restrictions remain visible.
Ambient OS confinement is reported separately, including `unobserved`; disabled SDK sandboxing
is not proof of unrestricted OS access. Mapping is preparation, not proof of target application.
The MCP execution gate has a narrower supported scope described in [Task tools](task-tools.md).

## Readiness and process lifetime

Before assigning implementation, check installed distribution/placement, native activation,
current policy and the active worktree claim separately. Preparation does not assume a new
worktree contains ignored installation files. The issuer arranges installation and reads the
preparation result. Readiness does not grant another actor a claim or evaluator authority.

Claude preparation drains the native Result and response iterator before submitting the
assignment as a separate query. Before that query, an owned SDK control request and native
readback revalidate the same session, prompt generation, policy, installation and claim.
A closed preparation turn is identified as an owned quiescent session; it is not relabelled active.

Durable admission returns a run ID before model work finishes. The detached worker receives
native events and emits creator-linked acceptance/start/wait/error/disconnect/cancel/completion
reports. Native turn completion does not prove task effects. The issuer reads the report body
and remains responsible for the next action.

Ordinary provider work has no task-lifetime timeout. Individual connection/write/response
operations can have deadlines. Event handling leaves message and cancellation paths usable.
`provider_status` diagnoses a recorded event or failure; it is not a completion polling loop.
`provider_cancel` requests cancellation and the resulting native report confirms the outcome.

An owned issuer connection stays available after a turn ends while issued work or
unacknowledged messages remain. An idle Codex issuer receives a new turn on that connection;
an active one receives steering using its actual turn ID. Claude uses the same SDK client,
but retains notifications durably while a response is active and submits them after its Result
and iterator finish. Mid-response input writes are not counted as separately acknowledged turns.
No heartbeat, periodic completion scan or separate receiver LLM is created. A closing connection
leaves late notifications recoverable; an input write already in progress finishes before close.
Already authorized work in another instance is not cancelled solely because the issuer dies.

## Durable delivery and repair

Messages commit before notification. The envelope preserves stable identity and immutable content;
repeated delivery carries the same key. The receiver reads the full body with `collaboration_message`
or another authenticated full-body lookup, then uses `collaboration_ack` or `collaboration_reply`.
An ID-only notification cannot satisfy body receipt. ACK means receipt, not acceptance or completion
of the assigned task. The LLM can recognize a repeated key; no exactly-once task-effect guarantee is made.

The owned delivery service retains unacknowledged `queued` and `submitted` messages. Failed,
uncertain and interrupted attempts remain recoverable. Database-change/native-readiness events,
registration and message-specific retry deadlines trigger delivery; retry backoff limits frequency,
not message lifetime. Held approval/input attempts await a relevant readiness event;
unavailable connections use per-message backoff. Endpoint generations and the owner lease
fence stale attempt results.

TTL and conversation budgets can restrict new messages, but do not discard accepted pending
messages. `collaboration_close` reports pending messages instead of silently closing over them.
Newsroom remains a separate transient active-peer feed.

`delivery_status(message_id)` returns the message status, recent attempt history and repair hold
for a participant. `delivery_redrive(message_id, expected_revision, repair_reference, key)` releases
an existing repaired hold for another attempt. Holds currently classify `envelope-version` and
`recipient-binding` problems. Redrive records the repair reference and preserves recipient, body
and key; the owning transport still validates delivery. It neither grants new rights nor restarts
task effects. A repair reference alone is not proof that the underlying defect is fixed.

## Provider process recovery

`provider_recover(run_id, key)` operates on recorded execution owned by the current issuer.
Admission requires the prior worker generation, recorded native session and verified process/connection
closure. An OS-held worker lease prevents competing recovery; an explicit cancellation is not revived.
Recovery keys reuse the existing admission instead of creating another logical execution.

The recovery worker restores the recorded native session on an owned connection, checks policy
and normal readiness, and reconnects delivery. It does not rerun the original assignment merely
because the receiver died. `recovery-accepted` is admission, not restored execution or receipt.
Missing closure evidence or an unrestorable native session produces a specific blocker and retains
recorded state. This does not promise automatic recovery from every abrupt crash or lost storage.

A Desktop-owned conversation still needs its own supported bridge for automatic wakeup. A detached
worker cannot claim that connection by reading shared history. This optional transport limit does
not reinstate an app/remote-observation gate for native collaboration.

## Verification scope

Current source entry points include `runtime/provider_execution.py`, `runtime/provider_policy.py`,
`providers/jobs.py`, `providers/job_recovery.py`, the Codex/Claude adapters, `agents/delivery.py` and
`agents/delivery_recovery.py`. Tests of these components are not installed-host acceptance.
Retain raw runs privately and distinguish schema/fixture checks, package installation, actual
mode/readiness, body lookup/ACK, process recovery and the subsequent issuer response. The final
installed Codex/Claude cross-provider and idle-issuer scenarios require their own native evidence.

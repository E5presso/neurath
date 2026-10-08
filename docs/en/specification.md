# Neurath requirements and acceptance specification

[Documentation](index.md) · [한국어](../ko/specification.md)

This specification defines the intended contract of the fresh Neurath design. A requirement here is not a claim that its implementation or live-host validation has passed. The local candidate version is **0.3.0**; this document does not announce a published release.

## Purpose and boundary

Neurath records accountable work: who requested it, who owns it, which stage it has reached, what was observed, and why it may finish. The MCP server has exactly one name: `neurath`. Protocol responses, database records, and host observations each establish only the facts they actually contain.

Neurath must preserve existing stored data and unfinished work when adopting the new design. It must not invent missing authority, evidence, ownership, or successful execution to make imported work appear complete.

## Concepts

| Concept | Responsibility |
| --- | --- |
| Session | An execution context with an explicitly identified native host and actor. |
| Source | The origin and authority boundary of a request. Its provenance remains attributable. |
| Task | A unit of work with an owner, revision, lifecycle stage, and recorded outcome. |
| Evidence | An observation or artifact supporting a specific assertion. |
| Delegation | A bounded request for another actor to perform work for an owning task. |
| Message | Attributed communication, with a recorded sender and recipient. |
| Checkpoint | A durable snapshot and note linked to a particular task revision. |
| Lease | An exclusive writer claim, protected by a generation that fences stale holders. |
| Receipt | A record that a specific event or decision was received from an identified origin. |
| Invocation | A record of a requested native action and its execution outcome. |

The domain is expressed independently of its database adapter. Repositories and a unit-of-work boundary provide persistence. SQLAlchemy implements storage; Alembic owns versioned schema migration.

## Ownership and authority

1. Every active task has an identifiable owner. A delegate may report its own work; that does not transfer ownership of the original task or source.
2. A human decision requires attributable human authority. Agent prose, another task's message, a successful tool call, or an imported status must never manufacture consent.
3. Native host identity must come from the host integration's verified context. A caller-supplied label alone cannot establish native provenance.
4. A report and an acceptance are different events. A delegate's reported result remains reported until an authorized owner accepts or rejects it under the task's requirements.
5. Changing ownership or accepting work must be an explicit, audited transition, not a side effect of reading a result.

**Acceptance:** attempts by an unrelated actor or stale lease holder to mutate an owned task are rejected without changing it. A delegation report alone cannot complete its parent. Missing human provenance cannot satisfy a human decision requirement.

## Ordered execution and completion

The lifecycle must distinguish understanding the request, defining an executable plan, doing the work, checking the result, and deciding completion. Phases are caller-defined ordered entries with an identifier and name; their states are pending, active, and completed. Task states are pending, active, waiting, completed, and withdrawn. The implemented vocabulary and legal transitions must be exposed consistently to callers. Advancing across a required stage must satisfy its prerequisites; reopening or retrying must preserve the prior history.

A completion decision must refer to the current task revision and the required, applicable observations. Terminal failure, cancellation, and successful completion are separate outcomes. A finished process, an empty queue, or an aggregate terminal flag does not by itself establish successful task completion.

**Acceptance:** out-of-order advancement fails with an actionable reason. A failed required check prevents successful completion. A checkpoint for an earlier revision cannot silently validate changed work. A failed attempt remains recorded and does not cancel the user goal. A retry preserves both its failed predecessor and the new attempt.

Stopping a host turn is distinct from ending the task. The first Stop hook requests continuation for unfinished work. A repeated stop with the host's `stop_hook_active` flag yields without discarding that work, preventing an endless blocker-report loop.

## Evidence has types and limits

Evidence must identify the assertion it supports, its origin, and enough context to associate it with the applicable task and action. In particular:

- A request receipt shows that a request was received; it does not prove execution.
- An invocation record shows an action's execution state; it does not automatically prove the intended result.
- A validation observation supports the check it measured; unrelated tests cannot substitute for it.
- A delegation report communicates a result; owner acceptance is a separate decision.
- A native host observation establishes what that host observed; discovery of a tool is not native execution.

**Acceptance:** substituting one evidence type for another fails when the requirement calls for a specific type or origin. A check whose native action never ran remains unverified. Stored evidence must remain attributable after restart and migration.

For configured checks, native pre-tool observation connects a prepared execution to the runner. The runner executes its stored argument list and persists the actual subprocess return code as evidence. Rendered tool output and printed success text are not authoritative substitutes. Execution start alone cannot satisfy a criterion; interruption requires inspecting persisted state before continuation.

## Concurrency and durable transitions

Task writes use compare-and-swap semantics against an expected revision. A transition and the records required to explain it commit atomically within a unit of work. A failed transaction must not leave a completed transition without its supporting records.

An idempotency key identifies one operation and its input. Repeating the same operation returns the original durable result without duplicating its effects. Reusing a key with different input fails explicitly. Idempotency is not permission to suppress a genuinely new action.

Lease acquisition and release follow explicit rules. A newer generation invalidates the authority of older holders even if they still possess an old token. A release must match the current owner, generation, and revision. The lease coordinates ledger writers; it grants no host permission.

**Acceptance:** two competing writes cannot both update the same expected task revision. Duplicate requests have one durable effect. Conflicting idempotency input is rejected. Rollback leaves no partial transition. A released lease or previous generation cannot authorize a protected write.

## Migration and recovery

Before adopting an existing database, preserve a recoverable copy and a record of what was preserved. Migration must retain the original data, including records that do not map into the new operational schema. Unfinished tasks must be identified and mapped explicitly; uncertainty must remain visible rather than being resolved through fabricated success.

SQLAlchemy is the runtime persistence layer and Alembic is the schema authority. Opening a database with a newer or unknown schema must fail clearly without downgrading or modifying it. Recovery instructions must identify both the archive and the active database unambiguously.

The emergency bypass must be usable even if the operational database is unavailable, malformed, locked, or too new. It must not need a successful database connection just to disable enforcement or explain recovery. Bypass is a recovery state, not task completion or validation success.

Worktree removal must preserve recoverable changes and a manifest before removing a checkout. A retained snapshot must account for tracked, untracked, and necessary ignored content. A cleanup operation must not claim recovery is possible until its backup has been checked.

**Acceptance:** a representative migration preserves all original data, explicitly accounts for unfinished tasks, and remains recoverable. Repeating migration does not create duplicate tasks. A future-version database is unchanged after rejection. Bypass still works with a deliberately unusable database. Removed worktrees can be reconstructed from verified recovery material.

## Installation and host activation

These are distinct observations:

| Observation | What it establishes |
| --- | --- |
| Source version | The code currently present in a checkout. |
| Installed distribution | The package or executable available to an installation. |
| Protocol availability | A reachable server offering a particular protocol surface. |
| Native host activation | The actual host has loaded and used the intended integration. |

No row automatically proves the next. A local passing test does not prove live activation, and a local candidate does not imply publication. Release, push, deployment, installation, and host restart require their own recorded scope and authorization.

**Acceptance:** status output distinguishes source, installation, protocol, and host observations and clearly marks unknown values. Live activation evidence names the host and the observed integration. Validation reporting separates tests actually run from checks still pending.

## Documentation acceptance

English and Korean documentation use matching paths and equivalent scope. Links within each language stay in that language except explicit translation links. User guidance uses natural-language workflows; agent and developer commands belong in the contributing guides. Public documentation contains no private filesystem paths or unrelated repository identifiers.

The feature guide lists only the fresh implementation's actual protocol surface. Unavailable features and unperformed validation are stated explicitly. This specification remains the acceptance target when implementation is incomplete; it must not be used as evidence that the target already holds.

# Neurath full redesign specification

[Documentation](index.md) · [Architecture](architecture.md) · [Acceptance](acceptance.md) · [한국어](../ko/specification.md)

**Rewritten design dated 2026-10-13, not deployed 0.3.1 behavior or an implementation-completion report.** This specification starts from the entire capability set and execution flow instead of adding missing features to the previous draft.

## 1. Purpose and reference

Neurath prevents unwarranted expansion and omission of user instructions and improves through reflection on actual execution. Intent must survive long runs, compaction, resumption, and delegation.

Original user instructions are the reference; tasks, procedures, memory, and checks serve them. Agents make necessary implementation judgments without inventing goals or shrinking requested work. Repeated historical assumptions are not new user instructions. Harness faults must not become obligations for users to repeat input.

**Retain the harness execution, memory and collaboration capabilities.** Scope includes TODO, Stop guards, phase runner, enclave, memory/handoff, collaboration, Newsroom, providers, skills/review/verification, and installation/update/finish. Do not copy historical implementation or faulty restrictions. Quietly removing capabilities or returning their work to the user is not a completed rewrite.

Neurath consists of **one core and three agent-facing surfaces**.

| Surface | Responsibility | Core connection |
| --- | --- | --- |
| Skill + rules prompts | Soft harness explaining that the agent works on Neurath, its procedures and CLI usage | Install the release-generated CLI guide and guide necessary state-management behavior |
| Hooks | Enforce next-action constraints at host boundaries such as tool execution/termination and automatically restore context after compaction | Apply decisions based on actual events and current core state through supported host controls |
| Typer CLI | Explicit reads/changes for tasks, phases, memory, enclave, newsroom, delegation and messages | Send agent invocations through the same core use cases |

**The core is a SQLite-backed structured memory persistence layer, a state machine, and messaging/collaboration infrastructure.** Persist originals/tasks/attempts/current facts/messages/assignments/outcomes and use state/events to determine valid transitions, next actions and waits. Connect message storage/delivery/reading/assignment/acceptance/results to manage collaboration. These roles are not separate services or duplicate ledgers.

Prompts guide behavior, CLI communicates with the core, and hooks enforce core decisions at actual host boundaries. Core state and transition rules are authoritative. Do not duplicate task ledgers or independent completion rules in hooks. A SQLite record alone does not execute/interrupt a tool or deliver a message; host adapters perform actual actions and return outcomes to the core.

### Core request-processing model

**Neurath Core is a stateless service.** Treat hook and CLI invocations like web-service requests. On each request, read the required current state from SQLite, process it through the use-case rules, persist necessary changes, and return a response.

```text
Hook or CLI invocation → request handling → SQLite state read → decision/transition → persist changes → response
```

**Use one SQLite database per local user.** All hook/CLI requests for that user use it regardless of project or working directory; identify projects/sessions and their relationships inside the DB. Do not create project- or session-specific database files. Scope related tasks/phases/enclave/messages/assignments/outcomes through their project/session relationships. Sharing a DB does not automatically inject unrelated project context; requested cross-project collaboration uses explicit relationships in the same store. **A Neurath project corresponds to one local Git repository.** Its main working tree, linked worktrees and subdirectories belong to the same project. Separate clones are distinct projects even with identical remote URLs. Codex app project groupings or host-specific working-directory labels do not replace this common boundary. Resolve identity through the local repository/worktree relationship, not remote-URL equality. For non-Git work, use the working folder as the project. Later git init retains the same project tasks and memory. Specify request/session project selection separately.

Durable agent/task/phase/enclave/message/assignment state lives in the database. Correct handling of the next request must not depend on the previous handler process's memory, a surviving core instance, or a continuously connected session. Request-local objects/computation are allowed but are not authoritative cross-request state.

This does not prescribe an HTTP server or a separately resident core daemon. Retain the prompt/hook/CLI surfaces; CLI and hook adapters invoke the same stateless core use cases. State that must survive agent execution remains in the DB.

The core state machine consists of transition rules applied to database state, not live agent objects held in process memory. Messaging/collaboration similarly uses persisted assignments/delivery/acceptance/outcomes per request. Use existing host adapters for necessary external actions and persist actual outcomes, without holding DB write locks across external calls. Coordinate concurrent requests through existing transactions/relevant revisions rather than process-local memory locks alone.

## 2. Components and responsibilities

| Component | Question it answers | Retained capabilities |
| --- | --- | --- |
| Task ledger/TODO | What was requested and what remains? | Sources, tasks/dependencies/outcomes, full progress display |
| Skills/phase runner | How does this selected procedure execute? | Start/current stage/actual execution/results/advancement/retry/resume/finalize |
| Runtime/Stop guard | Who is executing and may normal completion occur? | Sessions/turns/children, writer coordination, premature-stop prevention, explicit interruption |
| Enclave/memory | What is currently true and what supports it historically? | Bounded current facts, recall, checkpoints, receiver-led handoff |
| Collaboration/delegation/providers | Who was assigned what and did it run? | Discovery/messages/assignment/results/independent review/cross-host execution |
| Newsroom | Which findings help active peers? | Publication/headlines/body/comments/corrections/history/seen and active-peer notices |
| Reflection/learning | What changed and did later execution improve? | Cause/change/applicability/effect/reuse/reversal |
| Maintenance/distribution | Was work applied and finished without losing data or capability? | Diagnosis/bypass/recovery, install/release/update/finish-session/public reporting |

Connect components when needed. Do not force workflows and independent reviews on simple questions. Conversely, do not omit the phase runner or checks required by a selected skill.

## 3. Requests and outcomes

Preserve prompts and user-designated tickets/specifications and link them to necessary work and outcomes. One instruction can authorize necessary cross-project assignments.

Distinguish user originals from agent interpretation, assignment, and correction using conversational attribution. This is an interpretation rule against invented scope, not a new input-authentication or rejection system. Process agent-transmitted assignments, work, corrections and reports within existing user instructions. Do not reject messages en masse or demand a new human prompt merely because an agent sent them. Add no hashes, signatures, non-repudiation, consent certificates or separate approval ledger for this purpose. Use ordinary conversation context and existing request references; imperfect attribution does not stop work already supported by known instructions. Clarify only a genuine scope ambiguity that prevents deciding the next action.

Tasks distinguish `pending`, `active`, `waiting`, `succeeded`, `failed`, and `invalidated`. Preserve failed attempts and link still-applicable requirements to follow-up work or concrete blockers. All-terminal does not mean all-successful. Apply actual user cancellation/correction without requiring a special repeated approval phrase.

TODO projects the complete current ledger into the host. When display states are fewer, label actual success/failure/invalidation in the text. Stale or failed display submission does not change outcomes. Disclose unsupported display features and present the same information through an available surface.

Research, writing, implementation, and review use appropriate evidence. Retain reports with their assurance level instead of substituting unrelated process success for meaning. Bind verification to actual targets/checks/results. Reassess old success after target changes or later relevant failure.

## 4. Phase runner

Separate skill definitions from individual runs. A definition states purpose, stages, necessary inputs, work, outcome conditions, and transitions. A run retains its current phase, attempts, and actual results. Reading a definition or saying a phase passed does not advance it.

Connect ready-phase work to the executor or host and consume actual results to advance. Code evaluates mechanical conditions; designated reviewers evaluate content where required. Correction/review/retest iterations retain failures within the run. Resumption does not blindly repeat completed external effects.

Distinguish failure, waiting, skipping, and completion. Do not arbitrarily skip required phases; apply actual scope changes with their reasons. Preserve selected-procedure requirements without making phases, TODO, and checkpoints separate votes on ordinary completion. Tasks track user outcomes; the runner tracks the procedure used to obtain them.

## 5. Normal completion and actual interruption

Stop checks the target execution and current ledger. Reject normal completion while work remains, identifying the remaining work. Account for tasks added after an earlier read, stale events from other turns, and failure mislabeled as success. Elapsed time, status questions, and repeated rejection are not completion evidence.

User interruption, legitimate external waiting, exhausted allowances, and harness-failure pauses are distinct from normal completion. Actually yield control and preserve work, runner state, and enclave. A faulty hook must not demand endless continuation. Disconnection is not deletion or permanent termination of resumable work.

## 6. Enclave, memory, and handoff

Enclave is bounded current context: goals, corrections, established facts, decisions, and remaining work. Support read/update/delete with revision checks. Distinguish assumptions and facts and permit source retrieval. Historical reflection must not overwrite current facts or invent new requirements.

Project memory retains attributed history, checkpoints are handoff reports, and Graphify provides code/document relationships. After compaction/resumption, agents read enclave/tasks and retrieve relevant originals. Summaries do not replace sources.

A recipient can recover retained work without the original executor's final checkpoint. Context inspection is distinct from transferring work/writer ownership. Do not take a live writer's work forcibly, but provide legitimate resumption after confirmed termination/loss. Archival without a usable recovery route is incomplete migration.

Write enclave through CLI and automatically load it into model context through the post-compaction hook. Do not make both persistence and restoration depend on agent recall. Hooks read current core state.

## 7. Collaboration, Newsroom, and providers

Distinguish independent peers, native children, and provider sessions. Retain registration/discovery, questions/replies, inbox/full read/ACK, assignment/acceptance/progress/results/review/handoff. Persistence, actual delivery, reading, acceptance, and execution completion are distinct. Forward the original authorized scope without converting peer messages into new human consent.

Newsroom is project-local discovery/discussion. Preserve authors, evidence, revisions, and comments; notify active peers with headlines and identifiers only. Retrieve relevant bodies and apply corrections to work that actually relied on them. Do not wake waiting/ended sessions for news or inject every article everywhere.

Providers discover actual capabilities/models/policies and support planning/run/status/cancel/recover. Model selection differs from execution permission; unsupported inheritance must not silently substitute another policy. Connect only projects needed for the request; equal remote URLs do not automatically share separate clones/computers.

## 8. Outcome evaluation and retrospective

Tasks/TODO track required work and results. The Stop hook deterministically checks whether every task in the current session is complete. Neither failed nor waiting work counts as success; user cancellation, legitimate waiting and fault-related yielding are distinct from normal completion.

Delegate evaluation of whether the session's deliverable satisfies the user's original intent to a subagent separate from the executor or to another provider. Supply original instructions and current corrections, the full TODO list, actual artifacts and verification evidence. Compare against originals to find requirements missing from the TODO list itself. The reviewer reports fulfillment, evidence and unmet requirements rather than directly marking work successful.

Place third-party outcome evaluation in a phase of the skill that completes the user-requested body of work. Run it after gathering implementation/check results and before the completion report, not for each TODO, intermediate reply or status update. Manage it in the run responsible for that body of work; nested or finish skills reuse the same valid evaluation instead of repeating it. Confirmed gaps return execution to the relevant work phase, followed by evaluation of changed results. The associated task remains incomplete until the evaluation phase finishes; Stop deterministically checks task state only. Add no evaluation-only task or separate approval ledger. Do not recursively apply the same evaluation phase to reviewer assignments.

Reflect confirmed gaps in the same task list, perform the work and reassess changed results. Reuse valid evaluations when relevant instructions/artifacts are unchanged. Missing evaluation or failed delivery remains unverified; do not generate repeated model turns while waiting. Deterministic completion and content evaluation connect to the same work state without a separate approval ledger.

When issues surfaced during the session, offer a retrospective once at session end. On a user request or acceptance, delegate retrospective evaluation to a third party and use its findings for scoped improvement, validation, effect checking and retraction. The offer is not an instruction to execute; decline or silence does not block original-work completion. See the [interface specification](interfaces.md).

## 9. Cost, faults, and maintenance

External monitors trigger requested follow-up work on actual state changes. Do not call models repeatedly for unchanged waiting or create recurring automation without a user request.

Use SQLite with SQLAlchemy/Alembic to retain existing databases, unfinished work, sources, and historical ownership. Update only owned configuration and include backups/migration/resumption in cutover. Reads/diagnosis do not require writer leases. Official bypass suspends harness enforcement while retaining recordable data. Restore after actual recovery verification.

Retain release/update/public-reporting/finish-session capabilities. Execute within existing user authority, distinguishing genuine host approvals. Report actual evidence for behavior, documentation, installation, activation, and work completion separately.

[Architecture](architecture.md) defines completion/waiting decisions, delegation corrections, uncertain retries, and data cutover. Verify retained behavior through observable outcomes in the [capability map](capability-continuity.md) and [acceptance cases](acceptance.md). A completed document audit is distinct from live implementation validation.

## 10. Skill and CLI exposure boundaries

Installed rules are the default entry point; agents select skills appropriate to user requests. Follow explicitly named skills and do not force execution for simple conversation. The existing runner manages phases and results after startup. See the [skill entry specification](interfaces.md).

Retain capabilities without wrapping ordinary work in skills or exposing every internal transition through CLI. Use the [selected list](interfaces.md) of **14 skills and 19 CLI commands**. Commits/worktrees/issue and PR creation use host tools; checkpoint saving uses CLI; leases/ACK/Stop are internal. Selected project specialist skills remain usable. The historical 128 operations/33 skills are an omission-audit inventory, not installation counts.

Provide specification definition (including execution planning), implementation, review and QA as reusable skills; use define-spec, implement-spec and review-spec consistently. Excluding single host actions such as commits/worktree creation does not remove those procedures. Public CLI command names consistently use verb-object.

## 11. CLI-only distribution and pre-provided guidance

A Python + Typer CLI is the sole public execution interface. The redesign includes no MCP server/registration/optional adapter. Automatically generate a guide prompt from actual CLI definitions, validate it during release, and package it with that distribution. Installation/update places its body in the managed harness prompt so agents receive usage before invocation. See the [CLI specification](interfaces.md) for generation/application/recovery.

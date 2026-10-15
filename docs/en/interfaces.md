# Public skills and CLI commands

[Specification](specification.md) · [Capability disposition](capability-continuity.md) · [한국어](../ko/interfaces.md)

**User-audit revision: 2026-10-14.** Integrates specification/planning and UI implementation, separating user skills from internal self-improvement. This is a design, not an installed inventory.

Neurath consists of **one core and three agent-facing surfaces**.

| Surface | Responsibility | Core connection |
| --- | --- | --- |
| Skill + rules prompts | Soft harness explaining that the agent works on Neurath, its procedures and CLI usage | Install the release-generated CLI guide and guide necessary state-management behavior |
| Hooks | Enforce next-action constraints at host boundaries such as tool execution/termination and automatically restore context after compaction | Apply decisions based on actual events and current core state through supported host controls |
| Typer CLI | Explicit reads/changes for tasks, phases, memory, enclave, newsroom, delegation and messages | Send agent invocations through the same core use cases |

**The core is a SQLite-backed structured memory persistence layer, a state machine, and messaging/collaboration infrastructure.** Persist originals/tasks/attempts/current facts/messages/assignments/outcomes and use state/events to determine valid transitions, next actions and waits. Connect message storage/delivery/reading/assignment/acceptance/results to manage collaboration. These roles are not separate services or duplicate ledgers.

Prompts guide behavior, CLI communicates with the core, and hooks enforce core decisions at actual host boundaries. Core state and transition rules are authoritative. Do not duplicate task ledgers or independent completion rules in hooks. A SQLite record alone does not execute/interrupt a tool or deliver a message; host adapters perform actual actions and return outcomes to the core.

## 1. Selection criteria

A skill is a **reusable procedure with decisions, ordering and verification**, not only Neurath administration. Provide useful specification/implementation/debugging/review/QA/UI/documentation workflows. Dependency audits/updates belong to selected project/specialist capabilities rather than default Neurath skills. Commits/worktree or PR creation/simple edits are host operations, not separate skills. One test command differs from QA across user scenarios.

Expose CLI only for intentional agent commands or directly needed Neurath information, not CRUD per table. Consolidate current-work context queries and result reporting through the same task/attempt path. Do not hide unrelated effects behind `execute(action=...)`. The selected lists contain 14 skills and 19 core business CLI commands. Help/version and existing maintenance commands are separate; no MCP server or optional MCP adapter is provided.

### Core request-processing model

**Neurath Core is a stateless service.** Treat hook and CLI invocations like web-service requests. On each request, read the required current state from SQLite, process it through the use-case rules, persist necessary changes, and return a response.

```text
Hook or CLI invocation → request handling → SQLite state read → decision/transition → persist changes → response
```

**Use one SQLite database per local user.** All hook/CLI requests for that user use it regardless of project or working directory; identify projects/sessions and their relationships inside the DB. Do not create project- or session-specific database files. Scope related tasks/phases/enclave/messages/assignments/outcomes through their project/session relationships. Sharing a DB does not automatically inject unrelated project context; requested cross-project collaboration uses explicit relationships in the same store. **A Neurath project corresponds to one local Git repository.** Its main working tree, linked worktrees and subdirectories belong to the same project. Separate clones are distinct projects even with identical remote URLs. Codex app project groupings or host-specific working-directory labels do not replace this common boundary. Resolve identity through the local repository/worktree relationship, not remote-URL equality. For non-Git work, use the working folder as the project. Later git init retains the same project tasks and memory. Specify request/session project selection separately.

Durable agent/task/phase/enclave/message/assignment state lives in the database. Correct handling of the next request must not depend on the previous handler process's memory, a surviving core instance, or a continuously connected session. Request-local objects/computation are allowed but are not authoritative cross-request state.

This does not prescribe an HTTP server or a separately resident core daemon. Retain the prompt/hook/CLI surfaces; CLI and hook adapters invoke the same stateless core use cases. State that must survive agent execution remains in the DB.

The core state machine consists of transition rules applied to database state, not live agent objects held in process memory. Messaging/collaboration similarly uses persisted assignments/delivery/acceptance/outcomes per request. Use existing host adapters for necessary external actions and persist actual outcomes, without holding DB write locks across external calls. Coordinate concurrent requests through existing transactions/relevant revisions rather than process-local memory locks alone.

## 2. Skills

### Skill entry through rules

Installed rules are Neurath's default entry point. Users need not enable a separate mode or entry command for each task. Rules explain skill purposes, applicability, exclusions and CLI startup; the agent selects a skill according to the meaning of the user request. Follow an explicitly named skill when the user specifies one. Do not force skill execution for simple questions, explanations or status checks.

Skill selection is an agent judgment; the existing phase runner manages the selected definition, phases, attempts, results and completion conditions. Reading or mentioning a skill does not establish a started run. Start the selected skill through the existing `neurath start-workflow` path and inspect actual execution state. Selecting a skill neither expands the user request nor grants additional authority.

| Skill | Trigger | Procedure | Exclusions |
| --- | --- | --- | --- |
| `define-spec` | Define or refine user intent into an actionable specification | Intent/scope/alternatives → behavior/acceptance → execution order/dependencies/validation plan → decisions/open questions | Simple questions or unnecessarily redefining sufficient specifications |
| `implement-spec` | Implement behavior from specifications/requests, including UI | Specification/current behavior → scoped implementation → relevant checks → compare outcomes; include visual/state/interaction checks for UI | Trivial edits; neither an issue nor a separate plan is required |
| `autopilot` | An autonomous multi-task/dependency request | Original request → decomposition/assignment → execution/verification → unfinished-work reconciliation → outcome | One command, ordinary question, status read |
| `review-spec` | Audit requirements/specification/implementation alignment | Bind originals/scope → omission/expansion/contradiction cases → re-audit changes | Copy edit or ordinary code-diff review |
| `review-code` | Review changed code or a PR | Bind target/criteria → inspect execution paths → defects/impact → reassess fixes | Spec discussion or merely creating a PR |
| `qa` | Validate acceptance across user scenarios | Scenarios/environment → actual UI/API/persistence → outcomes/regressions | A single test command |
| `debug` | Investigate and repair an unexplained failure | Reproduce → distinguish causes → fix → regress the original failure | A predetermined small edit |
| `design-ui` | Design UI direction and user behavior | Purpose/flow → alternatives → states/interactions → record adopted direction | A single style-value change |
| `review-ui` | Review implemented UI behavior/usability | Actual UI and states → compare criteria → findings/recheck | Merely describing a screenshot |
| `sync-design` | Synchronize adopted design and implementation | Inspect both changes → establish source → scoped update → verify agreement | Inventing a new design direction |
| `sync-docs` | Update related documents/languages after source/spec changes | Changed facts → reader/page impact → write/synchronize → verify examples/links | A single typo fix |
| `pr-feedback` | Assess and address PR feedback | Compare current changes → classify validity → fix/verify → respond | Posting one comment |
| `finish-session` | Finish ongoing work with resumable handoff | Remaining outcomes/runner → relevant checks and third-party outcome evaluation → scoped Git/graph → handoff/ownership; optional retrospective offer when issues surfaced | Every conversational turn or a single commit |
| `update-neurath` | Install/update Neurath | Distribution/owned settings → quiescence/preservation → apply → live activation/resume | Version read or unrelated dependency update |

Name the specification workflow consistently: **`define-spec` → `implement-spec` → `review-spec`**. `define-spec` captures both desired behavior and how to execute/verify it in one specification. Execution order/dependencies/validation/finish planning belong there, without a separate `plan` call or duplicated document. Implement a sufficient existing specification directly; revise only affected parts when needed.

Merge `implement-ui` into `implement-spec`; apply UI-specific visual/state/interaction/accessibility references and actual checks when relevant. Keep distinct UI design (`design-ui`) and review (`review-ui`) roles.

Exclude `audit-deps`/`update-deps` from first-party defaults. Agents still perform needed dependency work through project tools or selected specialist skills; preserve existing user/project skills.

Do not ship `recover-session`. Existing **`resume-session` CLI** handles explicit resume/adoption, runtime handles automatic context restoration, and diagnostic/recovery commands remain usable when the operational store fails. No separate recovery skill is required.

`test-harness`/`optimize-harness` are not user-distributed skills. Retain their validation/improvement capabilities for Neurath development and the user-requested self-improvement process below. Merge `review-pr` into code review by target and audience-specific `dev-docs`/`user-docs` into `sync-docs`; reuse specialist Graphify capabilities.

Place third-party outcome evaluation in a phase of the skill that completes the user-requested body of work. Run it after gathering implementation/check results and before the completion report, not for each TODO, intermediate reply or status update. Manage it in the run responsible for that body of work; nested or finish skills reuse the same valid evaluation instead of repeating it. Confirmed gaps return execution to the relevant work phase, followed by evaluation of changed results. The associated task remains incomplete until the evaluation phase finishes; Stop deterministically checks task state only. Add no evaluation-only task or separate approval ledger. Do not recursively apply the same evaluation phase to reviewer assignments.

## 3. CLI-only interface

**The CLI stack is Python + Typer.** Define the `neurath` entrypoint and business/maintenance commands as a Typer application. Use Python type hints and Typer command/argument/option/help definitions; delegate domain behavior to Application use cases. Keep Typer dependencies in the CLI transport layer, outside Domain. [Official Typer documentation](https://typer.tiangolo.com/).

All names use **verb-object** kebab-case. Do not reexpose old object-first aliases. Action-named skills use kebab-case; established workflow names `autopilot` and `qa` remain.

| Tool | Inputs/outcomes and effect boundary | Effect |
| --- | --- | --- |
| `neurath get-context` | Read scoped session/task originals, TODO, assignments, runner, facts, peers/models, monitor/diagnostic summary; bound output with sections/filter/cursor | read |
| `neurath create-task` | Create work with original-backed outcomes and dependencies | write |
| `neurath update-task` | Revise scoped work/progress/wait/accept/cancel; cannot directly set success, passing checks or human consent | write |
| `neurath report-result` | Report scoped task/attempt/target results and evidence; only applicable responsible-actor outcomes drive task/phase transitions; delegate reports do not complete parents | write |
| `neurath start-workflow` | Start runner with pinned selected skill definition/inputs | write |
| `neurath revise-workflow` | Apply justified procedure revisions/retry/branch while preserving originals and required outcomes | write |
| `neurath delegate-task` | Assign/connect existing work to peer or provider with explicit necessary model/policy; redelivery cannot duplicate execution | write |
| `neurath send-message` | Send to recipients/subscribers; replies reference original message | write |
| `neurath read-message` | Read selected body; only confirmed full delivery produces read receipt, not understanding/acceptance | read+receipt |
| `neurath search-memory` | Search related memory/lessons/checkpoints/handoff candidates | read |
| `neurath read-memory` | Read selected record/evidence/handoff preview without changing ownership | read |
| `neurath save-checkpoint` | Save current outcomes/decisions/remaining work/references as a handoff report | write |
| `neurath resume-session` | Resume/adopt verified prior work, runner and context while preventing duplicate writers | write |
| `neurath update-enclave` | Apply revision-checked set/remove changes to current facts; never delete originals/tasks | write |
| `neurath list-articles` | List/search relevant newsroom headlines/revisions | read |
| `neurath read-article` | Read selected revision/body/comments; mark that revision read only after full delivery | read+receipt |
| `neurath publish-article` | Publish title/body/evidence and notify active peers with headlines | write |
| `neurath revise-article` | Revise an article with expected revision/reason, retaining history | write |
| `neurath comment-on-article` | Comment on selected article revision | write |

CLI commands call the same application use cases directly, without MCP registration/discovery/reconnection. Agents invoke them through host shell tools using the installed guide. Return structured JSON separately from logs/diagnostics. Exit status represents command handling, while results distinguish actual goal completion. Validate bad arguments before mutation and return actionable usage. Support file or stdin for complex bodies rather than guessing mutation retries. Define exact flags and formats with the real CLI definitions.

Business invocations run the selected installed version. New invocations use the updated distribution after cutover; settle in-flight calls at safe boundaries. The core retains no resident state. Verify version transition/handoff for in-flight host execution under its execution contract. CLI use alone does not automatically replace every resident process or rewrite an ongoing conversation's instructions.

## 4. Execution paths behind removed tools

- `get-context` provides bounded session/task/phase/fact/peer/model/message-headline/monitor projections. Default to concise current-work context, not unrelated history. Sections select documented read areas, never arbitrary internal methods. Large memory/message/article bodies remain explicitly selected reads.
- `report-result` binds outcomes to task/attempt. Recipients report; internal transitions require applicable responsible-actor judgment and actual evidence. Reports are not automatic success or owner acceptance. `update-task` cannot directly set success/evidence/consent.
- Peer delegation and provider execution are target choices of `delegate-task`. Internal adapters validate model/policy and execute. Observe through `get-context`; cancel the assigned work through `update-task`. Submission differs from actual launch/interruption.
- External monitoring belongs to a requested task's waiting dependency. `update-task` records the actual requested target/release conditions/allowed follow-up; the internal monitor observes that dependency. A waiting reason alone never authorizes arbitrary monitoring. Cancellation/resumption/handoff follow the same work lifecycle.
- `update-enclave` combines set/remove on one fact change set. Explicit remove plus expected revision is distinct from a null value.
- Peer subscriptions/conversation notification closure are project notification settings, read/edited with host file tools and consumed by runtime. They neither cancel assignments nor delete history; no per-turn CLI call is needed.
- Lesson generation/validation/deferral/retraction run within a user-requested retrospective. Read through memory tools. Explicit correction revises the attributed lesson source for runtime consumption while retaining prior effects/failures; learning cannot invent user instructions.
- Bypass/deep diagnosis/installation/update/DB repair use a maintenance CLI available outside the failed business-command path. `get-context` exposes healthy-runtime diagnostic summaries. `update-neurath` and runtime recovery use maintenance paths as needed; implementation docs define exact CLI syntax.

Distinguish user originals from agent interpretation, assignment, and correction using conversational attribution. This is an interpretation rule against invented scope, not a new input-authentication or rejection system. Process agent-transmitted assignments, work, corrections and reports within existing user instructions. Do not reject messages en masse or demand a new human prompt merely because an agent sent them. Add no hashes, signatures, non-repudiation, consent certificates or separate approval ledger for this purpose. Use ordinary conversation context and existing request references; imperfect attribution does not stop work already supported by known instructions. Clarify only a genuine scope ambiguity that prevents deciding the next action.

## 5. Preserved boundaries and validation

Stop/TODO projection/ingestion/separate observation and correction/actual leases and ACKs/phase finalization are internal. No tool manufactures identity/human consent/passing checks/read state without events. `read+receipt` is not purely read-only; uncertain full delivery leaves reading unconfirmed.

The runner retains selected skill definitions/current attempts/remaining outcomes. Renaming skills never deletes in-flight runs. Verify actual results for config/host replacements instead of handing work back to humans. Installers cannot arbitrarily delete project/user skills.

Acceptance checks cover exact discovery, verb-first names, replacement paths for 128 historical capabilities, specification (including execution planning) → implementation → audit connection, avoiding unnecessary skills for ordinary work, and result-author roles. A lower count alone proves neither simplicity nor retained behavior.

## 6. User-selected retrospective

Manage the retrospective offer and user-selected third-party retrospective evaluation as skill phases and branches. Decline or silence skips the optional retrospective branch and permits finishing; an existing request proceeds to evaluation without another offer.

When user feedback, execution failures or outcome review exposed issues during the session, and the user has not already requested a retrospective, offer it once while reporting the original work.

> This session exposed issues worth improving. Would you like a retrospective and self-improvement based on a third-party evaluation?

On a user request or ordinary conversational acceptance, delegate retrospective evaluation to a subagent separate from the executor or another provider. Supply user instructions, actual results and issue records; obtain causes, improvement candidates and evidence. The executor assesses the findings, implements scoped improvements and checks their effects against the failure and healthy cases. Retract regressions. Do not promote reviewer suggestions into user instructions or expand into unrelated work, publication or permission changes.

- Decline or silence means no retrospective. Do not block original-work completion, handoff or lease release, create an outstanding obligation, or repeat prompts/automatic retries in later turns or sessions.
- If already requested, proceed within that scope without asking again. Do not generate routine offers when no issue surfaced or merely because a conversational turn ended.
- Require no special choice token, hash, signature, consent object or new CLI command. Ambiguous replies are not acceptance; original work still finishes normally.

Retrospective evaluation, saved lessons and proposed improvements alone do not establish completed self-improvement. Report actual application and relevant validation separately. Run required checks within the requested retrospective rather than forcing full harness testing on every user task.

## 7. CLI guide prompt and release automation

**Actual Typer CLI definitions are the single source.** Read command descriptions, arguments, required values/enums, input/output, errors and verifiable examples from the same definitions as the CLI implementation. Do not maintain a parallel handwritten catalog or regenerate usage with an LLM every release. Do not distribute this design document as help for commands not yet implemented.

A release automation script must:

1. Deterministically generate a short agent guide prompt from the releasing code's Typer command/argument/option/help definitions.
2. Include distribution version, entrypoint, command purposes/required input, result handling, help on errors and necessary maintenance paths; leave detailed options discoverable through actual --help.
3. Check commands/options against the actual Typer parser. Validate examples with isolated data and no real publication/deletion side effects.
4. Fail release production if generation fails or the guide is stale. This is not a runtime approval gate blocking user work.
5. Package CLI and generated guide together at the same version.

Installation/update scripts insert or replace the guide's actual body in the **Neurath-managed harness prompt region**. Substitute only environment values such as executable location; do not regenerate semantics. A pointer to the guide alone is not pre-provided guidance. Preserve user instructions/project skills/other extensions; reinstalling the same version must not duplicate content. If executable/guide cutover fails, recover the matching prior pair.

Provide the guide before new sessions begin. For an active-session update, the success response supplies the changed version/usage and refreshed guide or causes an actual reread. A changed file alone does not prove the current conversation received it. Do not reinject the entire manual on every call or create repeated model turns after a guidance failure.

Generate at release time and apply during that release's installation/update. Publishing a release does not remotely modify every installation. Guide versions identify correspondence for diagnosis, not hashes/signatures/human-consent proofs or repeated user prompts.

Skills retain procedures and decision criteria; generated prompts describe actual CLI use. Do not add user-facing skills or MCP adapters merely because the CLI changed.

Neurath release automation generates the guide prompt from Typer command/help definitions. Prompt generation, packaging and installation are Neurath responsibilities, not assumed Typer built-ins. Reading definitions or rendering help must not execute business operations.

## 8. Enclave and hook responsibilities

**Separate enclave writes from context restoration.** Agents call `neurath update-enclave` to persist/update working facts, hypotheses, decisions and evidence in the core. Skills/rules and the generated CLI guide explain this use. A conversational statement alone does not imply persistence.

After compaction, do not wait for the agent to remember a read. The post-compaction hook reads the current session/task enclave from the core and automatically supplies it through a supported context output before the next model request. Keep `neurath get-context` for explicit inspection. No new public restoration command or skill is needed.

```text
Agent → update-enclave CLI → core SQLite state
Compaction completes → post-compaction hook → latest enclave read → model context → continue work
```

The hook does not infer new facts from the compaction summary and overwrite originals. Render bounded current facts/hypotheses/evidence for the relevant session/task. Do not restore corrected/deleted historical facts or mix another task's enclave. Startup/resume may reuse restoration, but manual invocation never substitutes for automatic post-compaction loading.

“Post-compaction hook” denotes the logical context-restoration boundary after compaction. Map it to current official host contracts using `SessionStart` + `compact` with `additionalContext` in Codex and Claude Code. An event named `PostCompact`, or stdout alone, does not prove context delivery. Keep native mapping in adapters and verify delivery to the actual next model input after both auto/manual compaction. [Codex hooks](https://learn.chatgpt.com/docs/hooks), [Claude Code hooks](https://code.claude.com/docs/en/hooks#sessionstart).

An empty enclave is normal and triggers no unnecessary work. Record read/injection failures as actual faults without fabricating restoration or generating endless model turns. Existing fault/wait rules govern genuinely missing information needed for current work.
Generated rules/CLI guidance explains that the agent operates on Neurath, how commands update core state, which working context belongs in enclave, and that hooks enforce next actions from core state. Guidance owns no separate execution state or new completion conditions.

# Public skills and CLI commands

[Specification](specification.md) · [Capability disposition](capability-continuity.md) · [한국어](../ko/interfaces.md)

This is the current CLI and installed-skill contract. File installation, native hook invocation, and actual model-context delivery require distinct evidence.

The [specification](specification.md) defines the core and its three surfaces; [architecture](architecture.md) defines execution, hooks and transitions. This page specifies skill selection and the public CLI contract.

CLI controllers follow the responsibility of each operation. `memory` handles memory reads, searches, reports and current-context updates; `session` handles handoff preview and resume. Moving the session option of memory read to session preview yields grouped public command paths.

## 1. Selection criteria

A skill is a **reusable procedure with decisions, ordering and verification**, not only Neurath administration. Provide useful specification/implementation/debugging/review/QA/UI/documentation workflows. Dependency audits/updates belong to selected project/specialist capabilities rather than default Neurath skills. Commits/worktree or PR creation/simple edits are host operations, not separate skills. One test command differs from QA across user scenarios.

Expose CLI only for intentional agent commands or directly needed Neurath information, not CRUD per table. Consolidate current-work context queries and result reporting through the same task/attempt path. Do not hide unrelated effects behind `execute(action=...)`. The selected lists contain 14 skills and grouped core business CLI commands. Help/version and existing maintenance commands are separate; no MCP server or optional MCP adapter is provided.

## 2. Skills

### Skill entry through rules

Installed rules are Neurath's default entry point. Users need not enable a separate mode or entry command for each task. Rules explain skill purposes, applicability, exclusions and CLI startup; the agent selects a skill according to the meaning of the user request. Follow an explicitly named skill when the user specifies one. Do not force skill execution for simple questions, explanations or status checks.

Skill selection is an agent judgment; the existing phase runner manages the selected definition, phases, attempts, results and completion conditions. Reading or mentioning a skill does not establish a started run. Start the selected skill through the existing `workflow start` path and inspect actual execution state. Selecting a skill neither expands the user request nor grants additional authority.

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

Do not ship `recover-session`. Existing **`session resume` CLI** handles explicit resume/adoption, runtime handles automatic context restoration, and diagnostic/recovery commands remain usable when the operational store fails. No separate recovery skill is required.

`test-harness`/`optimize-harness` are not user-distributed skills. Retain their validation/improvement capabilities for Neurath development and the user-requested self-improvement process below. Merge `review-pr` into code review by target and audience-specific `dev-docs`/`user-docs` into `sync-docs`; reuse specialist Graphify capabilities.

The skill completing a body of work runs the [outcome-evaluation phase](architecture.md#3-skills-and-phase-runner-contract). Nested skills reuse the same valid evaluation.

### Packaged definitions, installed instructions, and the runner

`resources/skills.json` contains the purpose, selection/exclusion conditions, required inputs, conditional branches, outcomes, and phase-specific result criteria and check names for each of the 14 skills. The same catalog produces installed `SKILL.md` instructions and existing `WorkflowDefinition` values. `define-spec` includes acceptance criteria, execution order, dependencies, and verification planning. `implement-spec` includes actual screen, state, interaction, and accessibility checks when UI is involved; it does not claim those checks for work without UI.

Installed files begin on the first line with YAML frontmatter containing `name` and a specific selection/exclusion `description`, followed by the instructions. Codex uses the corresponding folder under `.agents/skills`; Claude uses `.claude/skills`. Updating an owned skill preserves unrelated frontmatter fields and user text outside the managed block. Other project/user skills are untouched; an unowned skill at the same path is preserved rather than overwritten. See the [official Codex skill documentation](https://learn.chatgpt.com/docs/build-skills) and [Claude skill documentation](https://code.claude.com/docs/en/skills). Validating file format and installation does not prove native host discovery, selection, or model execution.

Reading a skill creates neither a run nor a phase result. Reuse the task and run already handling the current request. Call `task create` only for actual work missing from the ledger, and `workflow start` when starting a newly selected procedure. `workflow show --run-id UUID` reads the stored definition, inputs, attempts, and current phase. Package and source-file changes never overwrite an ongoing run. A different definition passed to `start` leaves the existing run intact and directs the caller to explicit `workflow revise`. Runs using older skill names remain readable and reportable from their stored definitions.

After actual host work, `workflow report` repeats `--check` for the current phase's verified `checks`. A normal phase report cannot pass independent result evaluation. Continue nested or finishing procedures by revising the same run while preserving an unchanged valid evaluation phase and its attempts. Related requirement/candidate changes require reevaluation through the existing evaluation path. Finishing alone does not create another evaluation task or recursively evaluate a reviewer. Changing the method is distinct from changing the user's goal.

### Selected project and user skills

The host can read and select an original `SKILL.md` outside the built-in list and execute its procedure through the existing runner. The agent passes an explicit definition faithful to that skill with `workflow start --task-id UUID --skill project-check --definition @workflow.json`. `--definition -` reads stdin; a JSON string is accepted inline. This does not require rewriting the original skill into a Neurath file or making the user manage internal state.

```json
{
  "version": "project-1",
  "source": ".agents/skills/project-check/SKILL.md",
  "inputs": {"target": "requested artifact"},
  "phases": [
    {"key": "inspect", "purpose": "Read the selected inputs", "checks": ["scope"]},
    {"key": "verify", "purpose": "Perform the project check", "result": "Verified actual output", "checks": ["content"]}
  ]
}
```

`version` and `phases` are required; each phase supplies `key`, `purpose`, and `checks`. Optional `inputs` maps names to string values. Optional `source` identifies an absolute path or a path relative to the actual working directory; the source text and resolved path are snapshotted in the run's inputs. A source read failure, malformed JSON, duplicate phase, or invalid check definition starts no task and saves no run. An unknown name without a definition returns the built-in choices and existing-run read/revision paths instead of inventing a procedure.

Ordinary host phases can have no executable arguments. The host performs the work with its tools and reports actual evidence. A selected procedure's required independent evaluation uses the existing evaluation phase; specialized skills do not automatically impose it on every operation. Commits, worktrees, issues/PRs, dependency management, Graphify, and recovery remain available through host/specialist tools and `session resume`.

## 3. CLI-only interface

**The CLI stack is Python + spakky-typer (Typer).** Define the `neurath` entrypoint and business/maintenance commands as a Typer application. Use Python type hints and Typer command/argument/option/help definitions; delegate domain behavior to Application use cases. Keep Typer dependencies in the CLI transport layer, outside Domain. [Official Typer documentation](https://typer.tiangolo.com/).

CLI Controllers declare an explicit functional group, and business commands belong beneath that group. When the group identifies the object, subcommands use verbs such as `list/read/publish`; use verb-object kebab-case when a further object distinction is needed. Action-named skills use kebab-case; established workflow names `autopilot` and `qa` remain.

Unimplemented action names below identify capabilities rather than instruct root registration. Define their explicit functional groups and final invocation paths when implementing them. Implemented commands show their group paths.

| Tool | Inputs/outcomes and effect boundary | Effect |
| --- | --- | --- |
| `context show` | Read scoped session/task originals, TODO, assignments, runner, facts, peers/models, monitor/diagnostic summary; bound output with sections/filter/cursor | read |
| `task create` | Create work with original-backed outcomes and dependencies | write |
| `task update` | Revise scoped work/progress/wait/accept/cancel; cannot directly set success, passing checks or human consent | write |
| `task report` | Report scoped task/attempt/target results and evidence; only applicable responsible-actor outcomes drive task/phase transitions; delegate reports do not complete parents | write |
| `workflow start` | Start runner with pinned selected skill definition/inputs | write |
| `workflow report` | Connect actual host phase results or acceptance/rejection of an independent report | write |
| `workflow revise` | Apply justified procedure revisions/retry/branch while preserving originals and required outcomes | write |
| `collaboration delegate` | Assign/connect existing work to peer or provider with explicit necessary model/policy; redelivery cannot duplicate execution | write |
| `collaboration observe` | Read or boundedly wait for the original assignment/report; never launch a new model | read+observed state |
| `collaboration send` | Send to recipients/subscribers; replies reference original message | write |
| `collaboration read` | Read selected body; only confirmed full delivery produces read receipt, not understanding/acceptance | read+receipt |
| `neurath memory search` | Search related memory/lessons/checkpoints/handoff candidates | read |
| `neurath memory read` | Read a selected historical memory and its evidence | read |
| `neurath session preview` | Preview a source session, originals, current tasks, runner and enclave without changing ownership | read |
| `neurath memory checkpoint` | Save current outcomes/decisions/remaining work/references as a handoff report | write |
| `neurath session resume` | Resume/adopt verified prior work, runner and context while preventing duplicate writers | write |
| `neurath memory update` | Apply revision-checked set/remove changes to current facts; never delete originals/tasks | write |
| `neurath newsroom list` | List/search relevant newsroom headlines/revisions | read |
| `neurath newsroom read` | Read selected revision/body/comments; mark that revision read only after full delivery | read+receipt |
| `neurath newsroom publish` | Publish title/body/evidence and notify active peers with headlines | write |
| `neurath newsroom revise` | Revise an article with expected revision/reason, retaining history | write |
| `neurath newsroom comment` | Comment on selected article revision | write |

CLI commands call the same application use cases directly, without MCP registration/discovery/reconnection. Agents invoke them through host shell tools using the installed guide. Return structured JSON separately from logs/diagnostics. Exit status represents command handling, while results distinguish actual goal completion. Validate bad arguments before mutation and return actionable usage. Support file or stdin for complex bodies rather than guessing mutation retries. Define exact flags and formats with the real CLI definitions.

Business invocations run the selected installed version. New invocations use the updated distribution after cutover; settle in-flight calls at safe boundaries. The core retains no resident state. Verify version transition/handoff for in-flight host execution under its execution contract. CLI use alone does not automatically replace every resident process or rewrite an ongoing conversation's instructions.

`memory propose-lesson` and `memory observe-lesson` preserve candidates and actual effects from requested reflection; `memory search/read` retrieves them. These commands are neither approval nor actual code application. `monitor status/tick` reads or observes a current monitor; native follow-up uses the [monitor callback](monitoring.md). `maintenance` owns installation, initialization, diagnostics, and independent failure journaling; `hook` owns host events. Ordinary calls resolve current project/session/peer/revision rather than requiring human bookkeeping.

`newsroom subscribe --enabled/--disabled` configures headlines for the current conversation without changing other topics, assignments, or history. New-native-peer defaults do not overwrite existing subscription choices.

### Scope and continuation

`context show` resolves the current host session automatically. `--session` selects another observed host session address; `--section` selects `current/sources/collaboration/memory`. In `current`, `--task-id UUID` narrows tasks and related runners/facts to a task owned by the selected session. Shared session facts and original-source references remain available so requirements omitted from TODO can still be found. A task belonging to another session, or a task filter in another section, is an error.

Each list defaults to 20 items; `--limit` accepts 1–100. Current context pages are output projections of the existing read-only handoff preview snapshot, not a bound on the entire database read. Bodies are not truncated mid-content. A list with remaining items always supplies a continuation cursor.

| Query | Continuation cursor | Order |
| --- | --- | --- |
| `context show` | `tasks/workflows/facts/source_ids` in `next_after_ids` | Existing query order: tasks by creation time then UUID; runners/facts by UUID; sources by creation time then UUID |
| `context show --section sources` | `next_after_id` in `{sources, next_after_id}` | Creation time then UUID ascending |
| `context show --section collaboration` | Inbox `next_after_id`, peers `next_peer_after_id`, assignments `next_delegation_after_id` | UUID ascending per list |
| `context show --section memory` | `memory_ids/applied_lessons` in `next_after_ids` | Newest creation first, UUID ascending for ties |
| `memory search` | `next_after_id` | Newest creation first, UUID ascending for ties |

Continue each list independently. Keep the same session, section, task/search filter and limit, pass that list's cursor as `--after UUID`, and collect **only that list** until its cursor is `null`. A full final page of memory search or applied lessons may be followed by an empty page. Do not merge different lists' cursors or treat a first page as the entire TODO or all original instructions. Recheck the latest first page when new tasks or corrections arrive between requests. To carry pagination metadata, the sources response now wraps the former bare array in an object with `sources` and a cursor.

```sh
neurath context show --section sources --limit 10
neurath context show --section sources --limit 10 --after <next_after_id>
neurath context show --task-id <task_uuid> --limit 10
neurath memory search --text "handoff" --limit 10 --after <next_after_id>
neurath maintenance version
```

`maintenance version` returns the name and version of the invoked installed distribution as JSON without opening or initializing the store. It works when the database is missing or corrupt. A version query does not establish host activation or update completion.

## 4. Execution paths behind removed tools

- `context show` provides bounded session/task/phase/fact/peer/model/message-headline/monitor projections. Default to concise current-work context, not unrelated history. Sections select documented read areas, never arbitrary internal methods. Large memory/message/article bodies remain explicitly selected reads.
- `task report` binds outcomes to task/attempt. Recipients report; internal transitions require applicable responsible-actor judgment and actual evidence. Reports are not automatic success or owner acceptance. `task update` cannot directly set success/evidence/consent.
- Peer delegation and provider execution are target choices of `collaboration delegate`. Internal adapters validate model/policy and execute. Observe through `context show`; cancel the assigned work through `task update`. Submission differs from actual launch/interruption.
- External monitoring belongs to a requested task's waiting dependency. `task update` records the actual requested target/release conditions/allowed follow-up; the internal monitor observes that dependency. A waiting reason alone never authorizes arbitrary monitoring. Cancellation/resumption/handoff follow the same work lifecycle.
- `memory update` combines set/remove on one fact change set. Explicit remove plus expected revision is distinct from a null value.
- Peer subscriptions/conversation notification closure are project notification settings, read/edited with host file tools and consumed by runtime. They neither cancel assignments nor delete history; no per-turn CLI call is needed.
- Lesson generation/validation/deferral/retraction run within a user-requested retrospective. Read through memory tools. Explicit correction revises the attributed lesson source for runtime consumption while retaining prior effects/failures; learning cannot invent user instructions.
- Bypass/deep diagnosis/installation/update/DB repair use a maintenance CLI available outside the failed business-command path. `context show` exposes healthy-runtime diagnostic summaries. `update-neurath` and runtime recovery use maintenance paths as needed; implementation docs define exact CLI syntax.

Assignments and attribution follow the [request interpretation rules](specification.md#3-requests-and-outcomes).

## 5. Preserved boundaries and validation

Stop/TODO projection/event ingestion/actual leases and ACKs/phase finalization are internal. No tool manufactures identity/human consent/passing checks/read state without events. `read+receipt` is not purely read-only; uncertain full delivery leaves reading unconfirmed.

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

Agents persist current facts, hypotheses, decisions and evidence with `memory update` and inspect them with `context show`. Generated CLI guidance explains what to retain and how to call these commands. The [enclave restoration](architecture.md#5-enclave-memory-graphify-and-pull) hook handles automatic post-compaction loading and failures.

## #146 Monitoring

[Monitoring observations, events, notifications, and candidate boundaries](monitoring.md).

[#138: Result evaluation and reflection implementation](result-evaluation.md)

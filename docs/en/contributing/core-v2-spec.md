# Neurath core replacement contract

[한국어](../../ko/contributing/core-v2-spec.md)

Status: design contract for the replacement core, not a description of the existing runtime or a claim of completed implementation.

## 1. Purpose and settled decisions

Neurath helps agents deliver the user's work and enforces the selected skill's procedure and the user's completion conditions. The host owns model execution, filesystem access and network permissions. The core does not implement a second host security boundary.

The decisions established on 2026-10-03 are:

| Decision | Contract |
| --- | --- |
| D1 | Rebuild from this specification rather than extend the existing core with exceptions. |
| D2 | Choose a subagent, independent session or Claude/Codex delegation according to task nature, difficulty and actual need. |
| D3 | An active skill cannot skip a defined phase or advance before its current phase completes. |
| D4 | An agent session cannot end normally with unfinished tasks. |
| D5 | Failure, blocking, timeout, passing checks or ending an attempt does not replace fulfillment of a user task. |
| D6 | Agent-written quotations, summaries and reports cannot replace original user instructions or actual observations. |
| D7 | Preserve installed projects' user files, host security settings and unfinished work independently of replacing the core source. |

An advisory-only task/phase system was rejected by D3 and D4.

## 2. Concepts and single responsibilities

| Concept | Meaning and responsibility | Not its responsibility |
| --- | --- | --- |
| Source | Immutable original user input or tool output observed through a host adapter, with provenance | Proving authority or meaning from prose or a hash alone |
| Actor | Host-identified participant executing or reporting work within a project | A separate authority principal bound to CWD or recreated for each worktree |
| Session | Host conversation/execution lifetime and the tasks it remains responsible for | A worktree, task or phase |
| Task | User-required outcome, scope, acceptance conditions, instruction sources and owner | The agent's selected check, attempt or recovery method itself |
| Skill run | Immutable snapshot of a skill definition and current phase attached to a task | Another completion ledger or a second goal |
| Phase | Ordered step and explicit completion conditions defined by a skill | An independent state machine requiring evidence prose |
| Assignment | Delegation of a bounded part of a task to another actor and its result-return contract | A new user instruction or implicit transfer of the entire task |
| Worktree lease | Conflict prevention that selects one actual writer for a checkout | A prerequisite for reads, review or diagnostics |
| Evidence | An actual observation or explicitly attributed agent report and its source | Truth guaranteed merely by citing a source |
| Approval | Permission for a specific action, target and scope grounded in actual user input | An agent's yes string, a peer instruction or an earlier similar approval |

Actor, session, task and checkout have distinct identities. Changing CWD does not change an actor's identity. The same actor may target another linked worktree within host permissions without creating another session.

## 3. State ownership

**Task is the sole owner of user-work progress.** It contains the current skill phase, completed phase records, acceptance results and assignment-result references. There are no separate workflow, adaptive and task completion ledgers to synchronize. The visible TODO is a projection of Task.

Use one transactional store per project. Mutation commands identify their target, expected revision and host invocation ID. The same invocation with identical input returns its retained result. Different input under the same invocation ID is rejected. Never bind work by matching goal prose, latest modification time or guessed state paths.

Sources, evidence and completed phase records are immutable. Changes reference a new user instruction or attempt rather than overwrite history. Host display status does not alter stored work state.

## 4. Task lifetime and session stopping

Task execution states are `open`, `running`, `waiting` and `completed`. `waiting` retains a reason and required external event and remains unfinished. Failure is an **attempt outcome**. There is no command to complete a task or erase its requirement because an attempt failed.

Task completion requires all of the following:

1. Every current user acceptance condition has a result and provenance.
2. Every phase of the attached skill run has completed in its defined order.
3. The owner has inspected and accepted required assignment and review results.
4. No mandatory condition remains failed or unsettled.

A user's change or cancellation preserves the original request as `withdrawn` history linked to the replacement. Withdrawal is not completion and requires actual user provenance. A status question, interrupted tool call or Stop denial is not a cancellation source.

Normal Stop is denied while the session owns any effective unfinished task or unsettled assignment. The response identifies exact tasks, current phases and necessary next actions. A Stop denial must never manufacture success, failure or cancellation.

Use the host's supported waiting state while awaiting user input. Waiting is distinct from normal termination. The core cannot physically prevent host shutdown, crashes or user interruption; it preserves unfinished work and recovers it on resume rather than treating interruption as completion.

## 5. Skill and phase enforcement

Read phase order and completion conditions from one definition distributed with the skill. Snapshot that definition and its version when attaching the run to Task. Installation updates cannot silently change a running phase's meaning.

| Command | Admission | Result |
| --- | --- | --- |
| Start | An actual task ID exists and the skill applies to its work | Select the first phase |
| Read current phase | The caller can observe the work | Return current phase and unmet conditions without mutation |
| Complete phase | The requested phase is current and every required condition is satisfied | Atomically complete it and select its successor |
| Complete last phase | The same conditions hold | Complete the skill run, allowing task acceptance evaluation |
| Record failure/block | An observed current-phase failure or external wait | Keep the current phase and append the attempt/reason |

Provide no general `skip`, arbitrary phase-index setter or `not-applicable` completion substitute. A conditional path must be defined by the skill in advance, including its condition, selection point and completion criteria. An agent cannot remove steps during execution.

Evidence uses defined reference types. PASS prose, regex-shaped text and lists of labels cannot replace actual check, review or publication results. Semantic acceptance identifies its assessor and evidence; the core does not claim to prove semantic truth. The skill determines when an independent review is required.

A phase may explicitly name subskills. A nested skill runs inside the same Task and returns to the unchanged parent phase after its own ordered phases finish. It does not complete the parent phase or expand its permitted effects. Undeclared subskills cannot replace a pending procedure. Task completion checks every attached skill run.

### Rework and actual effects

The skill predefines a `restart_from` phase for phase failures and final acceptance failure. A review finding starts another attempt of the same Task and executes the required phases again from that point. The failed review or observed changed input is the restart source. Preserve completed records as previous-attempt history; results at or after the restart boundary do not fulfill the new attempt. If inputs consumed by earlier results changed, restart from the earliest affected phase. Unknown impact restarts at the first phase. Reusing an observation requires the same condition, inputs and target revision and must not be reported as a new execution. There is no arbitrary phase-index setter or duplicate Task used to hide failure.

Before execution, the native adapter binds the actual tool invocation to Task/current phase and classifies its effects. The minimum classes are `read`, `edit`, `check`, `delegate`, `publish`, `cleanup` and `execute`. Each skill phase declares allowed classes. Known edit/publication/deletion tools and commands are denied when allowed only in a later phase. Registered checks are matched by exact argv and working directory. Mixed calls require every effect to be allowed. Unclassified shell/program calls are `execute` and are denied in read-only phases. The core does not claim static proof of every effect inside arbitrary programs; it preserves host permissions and reports its observation boundary. Known effects cannot be downgraded to generic execute.

Control commands such as state reads, failure reports and normal lease release remain separate from phase work effects. Ambiguous Task/phase binding denies writes with an exact selection requirement. Missing required host hooks such as PreToolUse return a capability gap before the affected effect, not a claim of verified enforcement. Reads, reporting and waiting for user input remain available. Actual-host acceptance must demonstrate denial of out-of-phase native edits and publication.

## 6. Delegation and review

Execution choices are `subagent`, `session` and `cross-provider`. Select using the task's nature, difficulty, necessary capability, independent lifetime and observed host support. Worker is the role of an actor performing an assignment, not a fourth execution choice.

- Subagent: bounded work within the current task; the default.
- Independent session: work needing its own conversation/lifetime; explicitly described as a new session.
- Cross-provider: work benefiting from the other provider's capability or perspective; retains the original purpose and result owner.

Repository-root entry, worktree need, duration and ticket count alone never mandate an independent session. Keep the host's explicit-request requirements for app projects and user-facing chats.

An assignment links the original task, bounded scope, parent, recipient and result. Parent/child lineage correlates calls and results; it grants no OS permissions. Native children and independent provider sessions return results through the same assignment contract.

Assignment roles are bounded `worker`, read-only `reviewer`, and `executor` responsible for the assigned Task's skill procedure. Roles are independent of the three execution choices. An executor may advance that Task's phases but cannot change its goal/acceptance/user approvals or finalize the user Task on the owner's behalf. Only one executor controls phases per Task at a time; the owner retains cancellation, report acceptance and responsibility recovery. Parallel workers act within the current phase while one controller advances it. Delegating a whole skill therefore does not duplicate its Task/phase ledger.

Independent review means a separate actor that did not implement the change assesses a fixed revision. Reading the checkout needs no writer lease or re-attestation of every execution-policy field. Unobservable policy remains `unknown`; it alone cannot block state reads or review reports. Actual writes and external effects still follow host permission enforcement.

A review is bound to a commit or diff digest. Changed work requires review of the affected scope. Do not accept unread reports, acknowledgments or worker termination as completion.

Assignment transitions are `issued → active → reported → accepted|rejected`. `reported` means the result is durably stored. This settles the recipient's return obligation; it may stop if it has no other unfinished Task/Assignment responsibility. The parent's inspection/acceptance duty remains, so its Task/session does not complete. Reporting must be possible before child termination.

A failure/block report returns the actual attempt outcome without satisfying parent acceptance. Rejection/retry creates another assignment attempt under the same Task and preserves the original result. Independent sessions executing a parent's attempt follow this rule too. An independent session owning a separate user Task cannot stop while that Task is unfinished.

## 7. Worktree ownership

Identify a checkout by Git common directory and canonical worktree path. Permit one concurrent writer. Claim, release and handoff are atomic transitions; an increasing generation fences stale writers.

Reads, diagnostics, analysis, review and failure reports require no lease. Task ownership and current writer are separate; delegation does not transfer the whole task.

An actor explicitly claims a selected linked worktree without fabricating CWD or session identity. The host decides whether native filesystem operations can access that path. Use separate worktrees for concurrent changes to the same files.

Never overwrite another writer's lease. Recover after normal release, explicit handoff or observed host termination. Elapsed time or agent assumptions alone cannot evict a live writer.

## 8. Provenance, quotations and approvals

Only the native adapter's observation path imports original native input and tool output as Source. Ordinary prompt hooks produce `native_input`; they do not attest that a human authored it. Documents submitted through general agent APIs are `agent_report`; matching bytes or hashes cannot promote them to user input or executed-tool evidence.

A quotation identifies a source and exact original span. Reject nonexistent text, text from another source and changed digests. External documents, peer messages and historical quotations cannot authorize current external actions.

Approval links action, target, scope and actual user input. Support clear direct instructions and actual replies to a uniquely pending question. Agent-written `user_confirmed=true`, option digests, XML/JSON shapes or quoted yes strings are not approval sources. Changed targets or scopes cannot reuse an earlier approval.

The working implementation verifies source bytes, exact quotations and action/target/task scope, while recording the agent's interpretation of user intent as `agent-interpretation`. It accepts retained native input for task intake without falsely upgrading its provenance to human attestation. Known peer, scheduled and continuation sources cannot authorize new work. The agent must distinguish genuine user instructions from automated input using the conversation context. Clear existing authorization remains usable without another confirmation question. This is the stated implementation assumption while the optional choice of a dedicated human-confirmation channel remains unanswered.

Hashes establish byte identity, not speaker identity or semantic consent. The core does not claim to isolate malicious tampering with host storage by another process under the same OS account.

## 9. Failure and recovery

Commands return success or a stable error code with the actual unmet condition and retained task ID. Missing task IDs and changed goal prose are not the same error; goal prose is never a binding key.

Diagnostic reads, recording failed/blocked attempts, reporting failed assignments and normally releasing an owned lease are distinct from executing task work. Failed execution prerequisites cannot block these recovery commands. Recovery commands do not complete tasks or phases.

Continue from observed state. New sessions, full-check reruns and new approval questions are not default recovery actions. Reuse completed observations when their inputs have not changed.

Resuming the same host session preserves Task ID and ownership. Transferring responsibility to another session requires explicit user direction or the prior owner's handoff and observation that the former writer stopped/released. Atomic adoption preserves Task ID while updating owner and ownership generation; stale-owner mutations are rejected. Already-issued assignment reports retain their original IDs and are accepted by the new owner.

User cancellation needs no replacement task. Preserve the original as withdrawn, deny new work in that scope and request cancellation of active assignments. Settle execution obligations and writer leases only after actual host termination or the recipient's cancellation report. A cancellation request alone does not prove process termination. Record user-forced interruption as observed and retain remaining cleanup for resume. Cancellation is never success.

## 10. Implementation boundary and removal

The replacement consists of domain models/transitions, one store, application commands and thin host adapters. Package installation, release/reporting transports and provider model communication remain outer services. They do not own separate task, phase or approval state.

Remove the old session kernel, duplicate task/phase/adaptive ledgers, review-specific state system, legacy CLI replay and prose-regex evidence gates from execution and distribution once the replacement meets its acceptance scenarios. A new facade over the old engine is not completion. Do not silently delete historical execution data or treat it as successful; preserve unfinished goals at an explicit export/adoption boundary.

Build a candidate distribution that excludes the old core first. After its actual-host acceptance scenarios pass, delete the previous implementation from the repository and verify the final distribution again.

## 11. Acceptance scenarios

| ID | Observable outcome |
| --- | --- |
| SC01 | A single root ticket can use a supported native path without a new session. |
| SC02 | Task grounds select independent sessions and cross-provider delegation, returning results to the original task. |
| SC03 | Skill phases execute in order; intermediate jumps and fabricated skips are denied. |
| SC04 | Finishing the last phase cannot satisfy unmet task acceptance conditions. |
| SC05 | Unfinished/waiting tasks deny normal Stop with the exact necessary next action. |
| SC06 | Interruptions/crashes preserve the same unfinished goal; failed attempts do not cancel it. |
| SC07 | Two writers for one checkout cannot both claim it; a reader can review/report without a claim. |
| SC08 | A linked-worktree change does not change actor/session identity or task ownership. |
| SC09 | Unknown child policy alone does not block read-only inspection or review reporting. |
| SC10 | Reject fabricated quotations, agent-created user approvals and approvals for another target. |
| SC11 | Bind actual direct instructions and exact pending-question replies without unnecessary re-approval. |
| SC12 | Identical retries return the same result; changed input/stale revisions cannot overwrite state. |
| SC13 | After state-recording failure, observation/block reporting/normal release remain possible without false completion. |
| SC14 | Preserve installed projects' user files, host permissions and unfinished records. |
| SC15 | No previous-core import, compatibility wrapper or duplicate progress store remains in the active distribution. |
| SC16 | A later review failure restarts defined repair/check/review phases on the same Task and preserves the earlier failure. |
| SC17 | A child may stop after storing its report; the parent Task remains unfinished until actual acceptance and fulfilled conditions. |
| SC18 | Authorized adoption preserves Task ID and rejects late mutations from the former owner. |
| SC19 | The actual host denies out-of-phase native edits/publication while allowing observation and failure reports. |
| SC20 | Actual user cancellation denies new work and settles active assignments only after their observed termination. |

Distinguish pure domain tests, real storage/concurrency tests, distribution installation and actual Codex/Claude end-to-end execution. Source tests alone do not establish host activation or delivered user work. The implementation plan links its work order and evidence to these scenarios.

## 12. Observed Codex integration boundary

The current [official hooks documentation](https://learn.chatgpt.com/docs/hooks) says a Stop block requests continuation rather than retracting an already displayed response. SessionEnd is advisory and cannot prevent user/host shutdown. Request continuation for premature normal completion and preserve unfinished work on actual interruption. A hook-generated continuation is not new human approval. Subagent hooks use the parent session_id and distinguish the participant by agent_id. Verify denial for observed PreToolUse paths, including edits and MCP; do not claim enforcement on unobserved paths. Recheck these boundaries on the actual installed host.

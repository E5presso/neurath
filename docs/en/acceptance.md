# Acceptance tests and implementation order

[Specification](specification.md) · [Architecture](architecture.md) · [Capability map](capability-continuity.md) · [한국어](../ko/acceptance.md)

**These tests are not implemented or passed yet.** They verify implementation against the requirements; the inventory is not a new mandatory procedure for every run.

## 1. Behavioral acceptance

| ID | Situation | Observable outcome |
| --- | --- | --- |
| A01 | Define work from prompts, designated tickets/specs, and actual corrections | Link originals and remaining outcomes without repeated direct input per chat |
| A02 | Third-party review of research-only work | Compare originals/current corrections and artifacts; identify out-of-scope changes without promoting review reports into user instructions |
| A03 | User requirement missing from TODO at registration | Third party compares originals and full results, reports omissions, and executor incorporates them into the same task list |
| A04 | Status question, correction, and old summary coexist | Apply only the correction; do not invent goals or drop other work |
| A05 | TODO changes across multiple tasks | Display the full current list and actual outcomes; submission is not success |
| A06 | A failed attempt leaves the original requirement unmet | Preserve failure and follow-up; distinguish terminal from successful |
| A07 | Start a selected skill through the runner | Read definition version/inputs/current phase/conditions and connect execution |
| A08 | A phase command actually fails | Retain failed attempt; do not advance required work before a justified retry |
| A09 | A phase requires independent semantic review | Consume the actual candidate/reviewer result rather than a claimed pass |
| A10 | Response lost after an external effect; runner restarts | Use read-back/deduplication first; with neither, retain unknown outcome without blind resend |
| A11 | Attempt to skip optional and required phases | Allow only defined conditions or actual scope correction; retain reason/history |
| A12 | User instruction or verification target changes mid-run | Reassess affected phases/evidence and preserve prior definitions/results |
| A13 | Finish the last phase, run, and task | No duplicate finalization; distinguish procedure completion from user success |
| A14 | New task added after a read before Stop | Deterministically inspect completion of every current task; reject stale-turn completion and new unfinished work |
| A15 | Repeated Stop, user interruption, external waiting, harness fault | Preserve work and actually pause/yield; rejection must not create infinite turns |
| A16 | Compaction/resume and concurrent enclave updates | Restore facts/goals/runner; reject stale writes and historical overwrites |
| A17 | Peer discovery, question, full reading, ACK, reply | Preserve actual address/author and delivery/read distinctions, subscriptions/close |
| A18 | Delegate lacks a direct user prompt | Execute/check/report assigned work while retaining original instructions/responsibility |
| A19 | Uncertain delivery, reconnection, late ACK | Recover original message; no ACK regression, duplicate execution, or endless redelivery |
| A20 | Newsroom publication with inactive peers | Headlines to active peers; selective body retrieval; no inactive wakeup |
| A21 | Article correction and comments | Retain authors/revisions/history and reassess dependent work |
| A22 | Provider planning, execution, cancellation, recovery | Verify actual model/policy/lineage without silent unsupported-policy substitution |
| A23 | Accept and publish independent review | Match candidate/current HEAD/results and user publication scope |
| A24 | Adopt work without a final checkpoint | Retain sources/tasks/runner/enclave/writer responsibility and fence duplicate writes |
| A25 | Apply user-requested reflection in later relevant work | Verify effect/retract harmful lessons without unauthorized goal/permission/rule changes |
| A26 | Graphify update includes document relationships | Preserve/check semantic relations; exit status alone is insufficient |
| A31 | Reads, concurrent writers, executor termination | Reads need no lease; coordinate writes and recover safely after termination |
| A32 | Code changes or related failure after a passing check | Do not rely solely on old success; rerun relevant verification only |
| A33 | Check interruption, timeout, large output | Honor timeouts, record interruption, bound output storage, support retry |
| A34 | Migrate existing databases and unfinished records | Preserve originals/WAL; verify mappings/resume/rollback; unknown is not zero |
| A35 | Install alongside other hooks/CLI/project instructions | Update/verify owned configuration only; verify and reuse identical installation |
| A36 | CLI error, storage failure, bypass, restart | Retain actual failure/recoverable state without losing original instructions |
| A37 | Unchanged waiting, PR monitoring, output fragments | Zero additional model calls during unchanged waiting; assess actual changes |
| A39 | Full retained operation and skill coverage | Map every capability to executable use cases/tests, not names-only or manual replacement |
| A40 | Update and finish all connected projects | Verify distribution/install/activation/work/runner/Git/graph/ownership/coordination finish |
| A41 | Prepare and submit public reports/contributions | Check publication scope/sensitive data/actual submission without automatic scope expansion |

### Boundary and race counterexamples

| ID | Situation | Observable outcome |
| --- | --- | --- |
| A42 | TODO complete but deliverable does not fulfill user intent | Independent evaluation reports evidenced gaps for incorporation into the same task list |
| A43 | Relevant user instructions or artifacts change during evaluation | Reassess affected results only; unrelated changes/evaluation bookkeeping do not create reassessment loops |
| A44 | Invented input wait, real dependency and independent work coexist | Perform already-authorized/independent work; wait only for real dependencies; report actual needed action |
| A47 | Parent correction/cancellation followed by late receipt/result/redelegation | Propagate affected scope only; no new cancelled work; expose unconfirmed interruption; old results cannot close current requirements |
| A48 | Attempt A times out, B starts, A succeeds late | Retain A history without passing B/current definition |
| A49 | Mutation response lost with neither lookup nor deduplication | Unknown-outcome wait and notification, no automatic repeat, independent work continues |
| A50 | Old writer reconnects and new events arrive during DB cutover | Reject old writes; retain/replay events in order; one writer path; no cutover without confirmed quiescence |
| A51 | Rollback after new-version writes | Retain new records/pending events; lossless compatible return or pause writes and resume through repair version |
| A52 | Pending/failed independent evaluation or hook fault at Stop | Retain unfinished/unverified state and return control without repeated turns or fabricated success |
| A53 | User interruption/cancellation with late replies from another turn | Confirm actual interruption of the target, distinguish prior responses and never automatically resume cancelled work |
| A54 | Notification submission fails, unchanged wait, reconnect | Persist failure/action in status; bounded delivery retry; no repeated executor calls |
| A55 | Cleanup with dirty/unmerged/untracked/needed ignored content | No deletion before scoped preservation/recovery checks; verify remote refs and other writers |
| A56 | Enclave deletion, unsubscribe, news revision, learning deferral | Reject stale deletion; no publish after unsubscribe; old seen does not mark new revision; defer is not success |
| A57 | Exercise historical capabilities through selected public/internal/host paths | Observe necessary outcomes of the old 128 operations/33 skills; old names are not required and work handed back to humans remains unimplemented |
| A58 | Waiting outcome becomes known, then an unrelated requirement changes | Reconcile the same attempt and retain unaffected artifacts without re-execution |
| A61 | DB and notification delivery fail together | Expose unfinished work through available host/recovery surfaces; impossible delivery remains unconfirmed; no inference loop |
| A62 | Managed execution passes but actual user connection remains untested | Do not report full rollout until actual hook/CLI/delegation outcomes are verified on that connection |
| A63 | Commit/worktree creation/simple code explanation | Use host tools without unnecessary skills/runners |
| A64 | Inspect core CLI and default skill lists | Match 19 core commands/14 skills; no MCP server/adapter or reexposed internal aliases |
| A65 | Leases/ACK/finalization and truncated body | Derive internally from actual events; no fabricated identity/consent/success; truncated body is not confirmed read |
| A66 | Run selected default and project specialist skills | Complete their procedure/outcomes; default removal is not capability deletion or human handwork |
| A67 | Public interface changes during an old skill run | Retain pinned definition/original work; direct cached calls to replacement; preserve project skills without failure loops |
| A68 | Specify behavior/execution plan and implement including UI | define-spec includes requirements/behavior/execution order/validation; implement-spec performs UI checks without separate plan/implement-ui calls |
| A69 | Context/result/review/delegation for the same work | Bounded context, attributed role/evidence, no duplicate delegation or arbitrary dispatcher |
| A70 | Inspect public command names and help | 19 core neurath verb-object commands; actual help and installed guide agree |
| A71 | Validate/apply improvement during a user-requested retrospective | Start from ordinary conversational instruction; controls/effect/retraction; no user-facing harness skill or consent certificate |
| A72 | Context loss or explicit session resume/adoption | Automatic restoration or resume-session retains originals/unfinished work/runner without a recover-session skill |
| A73 | Peer conveys work within existing instructions | Perform normally; nonhuman authorship alone triggers no rejection, repeated human input, hash or signature |
| A74 | Session-end retrospective offer when issues surfaced | Ask once normally; no retrospective evaluation/persistent improvement before acceptance; original work may finish |
| A75 | No request, declined/unanswered offer, or no session issues | No retrospective, repeat prompting, automatic retry, outstanding obligation or completion block |
| A76 | User requests or conversationally accepts retrospective | Use the skill user-selected branch to delegate retrospective evaluation to a separate subagent or another provider, then perform evidenced scoped improvement/validation/application without repeated consent or special tokens |
| A77 | Generate prompt from actual releasing Typer definitions | Match actual commands/arguments/examples; deterministic output; stale/failed generation fails release production |
| A78 | Install/update CLI with its guide | Install matching-version prompt body; preserve user settings; no duplicates; restore matching pair on failure |
| A79 | Supply updated usage to new and active sessions | Verify pre-provided guide or actual reread/update response; file mutation alone is not context refresh |
| A80 | CLI-only cutover with in-flight work | No MCP server/registration/adapter; distinguish new and in-flight invocation versions and retain work |
| A81 | Update enclave through CLI, then auto/manual compaction | Post-compaction hook injects current relevant contents into the next model input without an agent get-context call |
| A82 | Corrected/deleted/other-task/empty enclave and hook failure | Restore current scope only, no stale/deleted resurrection, empty state normal; no false delivery or repeated turns on failure |
| A83 | Next tool use/termination after core state changes | Hook enforces current core decisions rather than relying on prompt cooperation; preserve condition resolution and recovery paths |
| A84 | Same task/phase/memory/collaboration across all three surfaces | Prompt guidance, CLI mutation and hook enforcement share core/SQLite state without separate authority/completion ledgers |
| A85 | Process the same work in distinct hook/CLI request processes | Continue state/transitions/outcomes by DB reads without prior process memory, core daemon or continuous connection |
| A86 | Concurrent requests and request failure | Coordinate through existing DB transactions/revisions without leaking uncommitted state or relying only on in-memory locks |
| A87 | Multiple projects/sessions use one user store | Use one physical SQLite DB; retain project/session distinctions; same local names or cwd changes cannot overwrite/inject unrelated records |
| A88 | Main tree, linked worktrees and subdirectories of one Git repository | Use one Neurath project while retaining distinct sessions and actual working paths |
| A89 | Separate clones with identical remote URLs | Keep distinct Neurath projects; remote URL or host UI project name alone cannot merge records |
| A90 | Delegate session outcome evaluation to a subagent or another provider | A reviewer separate from the executor assesses originals/current corrections/full TODO/artifacts/evidence; reuse unchanged valid evaluation |
| A91 | Mixed succeeded/failed/waiting tasks or all tasks complete | Stop uses current task state without model judgment; failed/waiting is not normal completion, while legitimate yielding remains allowed |
| A92 | Body of work with multiple TODOs/intermediate replies/nested skills | Responsible skill runs evaluation before completion report; gaps return to relevant phases; reuse valid reviews; no separate evaluation task or recursive evaluation |
| A93 | Work request without entry command, explicitly named skill, or simple conversation | Rules guide appropriate skill selection and CLI startup; respect explicit selection; no unnecessary run for simple conversation; existing runner manages phases |

## 2. Implementation order and deliverables

1. Validate hook/CLI requests → SQLite reads/transitions → actual host enforcement in disposable work.
2. Connect originals/tasks/TODO → phase runner → actual results → third-party outcome evaluation → deterministic Stop, with enclave restoration. Manage evaluation as a phase of the responsible skill and reflect it in the associated task state.
3. Connect peers/children/providers, Newsroom, memory/handoff, third-party evaluation for user-requested retrospectives, learning, Graphify and selected skills.
4. Verify healthy cases and omissions/scope changes/cancellation/failure/compaction/restart. Include mistaken reviewer findings and resolve them against user instructions and evidence.
5. Test migration/rollback/resumption on copies of actual data, then perform requested release, project updates, live activation and finish-session.

Record implemented outcomes and unfinished work at each stage. Documents or simulated tests do not establish actual host validation or full implementation completion.

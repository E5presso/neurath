# Core replacement implementation plan

[한국어](../../ko/contributing/core-v2-plan.md) · [Core contract](core-v2-spec.md)

Status: replacement source is implemented and the previous core source is removed. Full source checks passed; later review fixes have focused regression evidence. Final package validation and live host activation remain separate. The narrow routing patch is not the foundation of this replacement.

## Scope and transition

Contract decisions D1–D7 and scenarios SC01–SC20 define acceptance. Prepare 0.2.0 to distinguish the incompatible core replacement. Preserve existing installations and data until the new distribution is verified. Do not install development source into other active projects.

The new center is `src/neurath/core/`. It replaces control/state implementations in `runtime/`, `hosts/`, `agents/` and the bundled `scripts/agent_harness` and `scripts/skill_harness`. Review and retain necessary outer functionality in provider wire transports, installation preservation/rollback and public release/reporting services while removing their old-core dependencies.

## Stable internal contracts

- `Context`: adapter-observed project/session/actor/invocation, never supplied through public command arguments.
- `Task`: ID, revision, user source references, goal, acceptance, owner session, execution state, skill run and assignment references. Goal prose is not an identifier.
- `SkillDefinition`: ID/version and ordered phases with completion conditions and allowed effect classes; snapshotted into Task on start.
- `Evidence`: source kind/ID, observed result or attributed actor report and target revision. Agent documents cannot acquire native provenance.
- `Assignment`: ID/task ID, one of three execution choices, rationale, scope, issuer/recipient, state and report. Reported settles the recipient return obligation; the owner accepts it toward task completion.
- `Lease`: canonical checkout, writer and generation. Paths identify lease targets, not actors.
- `Approval`: action/target/scope bound to actual user input. It does not change permissions or OS confinement.

Application commands use `Context + command -> result` and one store transaction. Reads require no other workflow's admission. Native adapters perform external effects, separately checking the current phase's allowed effects and the host's permissions.

## Work units and dependencies

| Unit | Deliverable | Prerequisite | Scenarios |
| --- | --- | --- | --- |
| A1 | Source/Actor/Task/Skill/Assignment/Lease/Approval models and pure transitions | Specification cold-read | SC03–SC13, SC16–SC20 |
| A2 | Single transactional store, revision checks, exact replay and immutable sources | A1 | SC07, SC10, SC12, SC13 |
| A3 | Task/phase/Stop/rework/adoption commands and closed input schemas | A2 | SC03–SC06, SC13, SC16–SC20 |
| B1 | Codex/Claude native observations and distinct read/write/report admission | A3 | SC01, SC07–SC11, SC19 |
| B2 | Three delegation paths, assignment reports/acceptance and provider effects | B1 | SC01, SC02, SC09, SC17, SC20 |
| B3 | Skill definitions/prose, TODO and installer/MCP/CLI connection | A3, B1 | SC03–SC05, SC14 |
| C1 | Candidate distribution excluding the previous core; explicit data export/adoption | B2, B3 | SC06, SC14, SC15, SC18 |
| C2 | Old-source removal, final distribution/independent review and candidate actual-host validation | C1 | SC01–SC20 |

A1 is the reference implementation for subsequent units. The critical path is A1→A2→A3→B1→B2/B3→C1→C2. B2 and B3 can partly run in parallel with separate provider and skill/install ownership; shared schemas and adapter interfaces integrate sequentially. An all-parallel plan is not approved.

Do not split cohesive behavior into bookkeeping-only tickets merely to meet a line-count target. Each unit supplies complete invariants and executable acceptance scenarios. Shared models/schemas have one integrating writer.

## Verification

1. Write executable positive and negative scenarios before production behavior.
2. Exercise actual SQLite transactions, concurrent writers, stale revisions and duplicate invocations.
3. Exercise both host event shapes across prompt/source, child, tool and Stop flows.
4. Deliver a narrow ticket through the installed distribution. Native child review must support authorized reads/reports without the parent's writer lease or a complete policy snapshot.
5. Verify that failed checks, broken connections and user interruptions preserve the current phase and required task.
6. Combine package integrity, installation preservation, host end-to-end and independent review evidence only after their individual results exist.

Retain tests of preserved installer/release behavior. Replace tests of deleted internal structures with scenario-level behavior tests. Do not remove failing tests without an explicit contract mapping or route the new core back through the old engine.

## Decisions and unresolved host observations

The user rejected advisory-only task/phase tracking. Denying skipped phases and normal termination with unfinished work is mandatory. Preserve provenance checks and actual host permissions. Remove the requirement that read-only reviewers establish writer readiness.

Host event delivery, app visibility of independent sessions and native target-path support are observations to obtain in B1/B2 and C2, not assumptions to declare verified. Unsupported functionality returns precise capability results and does not block work-state reads or failure reports.

Retain progress, design disagreements and actual verification in this plan and the [core contract](core-v2-spec.md). A fresh session must be able to resume from these files and current source/tests.

## Cold-read corrections

The first independent review identified four missing contracts: rework, assignment reporting versus acceptance, owner-session loss/cancellation, and actual phase-effect admission. All were accepted. Sections 5, 6 and 9 now specify transitions and responsibilities, tested by SC16–SC20. Rework starts another attempt of the same Task at the skill-defined restart_from. Reported separates child return obligations from parent acceptance. Adoption preserves Task ID with an increased ownership generation. Native effect classes include actual out-of-phase edit/publication denial. Source removal is reversible in Git and is independent of switching an already installed host. Actual-host proof remains required before claiming activation.

## Implementation progress — foundational model and store

`src/neurath/core/domain.py` implements Task-embedded skill runs, ordered phases, rework, assignment reporting/acceptance, original-span quotation and Stop decisions. `codec.py` and `store.py` own one SQLite transaction boundary, revisions, exact replay, immutable sources and writer lease generations. `service.py` accepts adapter-provided Context and excludes actor/native-provenance creation from public arguments, binding commands by Task ID. The initial domain/store/service behavior tests pass. This is foundational A1–A3 work; approvals/delegation transports, actual host hooks, installation and old-core removal remain unfinished.

### Native ingress foundation

`host_events.py`, `hook_adapter.py`, `tool_schema.py` and `mcp.py` add native session/agent identity independent of CWD, original native-input retention without human attestation, exact-invocation MCP binding and retirement, current-phase effect admission and Stop projection. Declared nested skills return to their parent phase and cannot widen its effects. A real stdio process exposes the new command surface without importing the old engine. Core tests cover these foundations; this is not installed-host validation. Explicit terminal check results are now captured against the source bytes, and changed sources cannot consume stale checks. Native edit destinations, Task adoption/withdrawal and exact-target interpreted approval are connected. The new typed catalog preserves all 29 existing phase sequences; skill prose/projection and conditional paths still require migration. Provider dispatch, preserved outer services, installer cutover and actual-host proof remain pending. These initial checks are superseded by the integration progress below.


### Rework, skill integration and installation entrypoints

Rework now waits for bounded assignments to settle. Native checks retain the originating run and every enclosing attempt; changed or unknown inputs reject historical results even when the result arrives after restart. Explicitly unchanged inputs permit reuse of the same source observation. Independent reproduction and revalidation covered both paths, including persistence and nested parent restart. These are scoped reviews, not the final release review.

The 29 contracted skill entrypoints, implement-issue/autopilot phase documents and shared execution rules now use the single Task contract. Autopilot retains issue-level Tasks, the three execution choices, explicit nested review/documentation skills and defined recovery paths. Catalog validation rejects nested skills whose effects cannot run within their parent phase. Remaining maintenance skills and supporting scripts still need integration.

Installer MCP settings use provider-specific new-core adapters without generated permission overrides. Hook callbacks use the installed interpreter and common project root independently of the active checkout. CLI discovery, installer planning and both hook-protocol subprocesses run with imports of the retired core forbidden. The old generic engine/skill command gateway is removed. Installer rollback/history remain in the retained outer service. Data transition, old bootstrap compatibility, candidate packaging and actual-host activation remain unfinished.

The last complete focused core run passed 150 tests; later installer/CLI changes have additional targeted checks. Full repository validation and final independent review remain required. No installation, merge or public release is implied by these results.

## Source replacement status

The previous `runtime`, `hosts`, `agents`, bundled script engines, obsolete provider orchestration and skill helper implementations have been removed from development source. This source change does not switch an already installed immutable runtime. Candidate packaging no longer serves as a reason to retain the previous implementation in source. Final activation and public release still require their own evidence.

Tests tied to the removed implementations are retired with those implementations. Their required contracts move to `tests/core`: Task/phase/Stop and rework (`test_domain`, `test_service`, `test_hook_adapter`); concurrent state and writer ownership (`test_store`, `test_workspace`); assignment/report/acceptance and the three delegation choices (`test_collaboration`, `test_native_delegation`, `test_provider_commands`); input and quote provenance (`test_service`, `test_host_events`); actual check and publication results (`test_checks`, `test_native_results`, `test_publications`); preserved state and installation (`test_legacy_work`, `test_install_storage`, `test_install_entrypoints`). Existing outer-service installer, release, reporting, transport and learning behavior tests remain. Test replacement is not a claim that every actual-host scenario is verified.

Actual Claude sessions have demonstrated phase-order rejection, continuation of the same unfinished Task after Stop rejection, and a failed native check whose printed success text cannot override exit code 7. Codex candidate hook definitions remain untrusted in the test host, so the corresponding live Codex result is unverified. That specific host boundary does not block source development, data-transition implementation, packaging checks or independent review.

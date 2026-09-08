# Dynamic model planning and MCP operation contract

**English** · [한국어](../../ko/contributing/model-planning-mcp.md)

[Architecture](architecture.md) · [Task tools](task-tools.md) · [Provider transports](provider-transports.md) · [Collaboration contract](collaboration-contract.md)

Status: accepted implementation specification. The user requested difficulty-aware model planning
when starting a provider or session, and reliable migration of agent-operated harness commands to
MCP. These are target requirements, not claims of implementation or native acceptance.

## Intent, decisions and vocabulary

For each authorized new provider/session, the agent plans model selection from the actual assignment,
current availability and existing constraints. Users describe outcomes in natural language; the agent
owns discovery, planning, execution and verification. Planning does not authorize additional sessions,
switch the current model, expand permissions or override a user-specified model/provider.

- D1 (user): plan model selection dynamically according to task difficulty.
- D2 (user): operate the harness through MCP and coordinate overlapping sessions.
- D3 (derived): use current provider/host inventory, not a hard-coded commercial model ranking.
- D4 (source): preserve requested/actual model checks, identity, ownership and execution policy.
- D5 (derived): migrate generated instructions as well as tools; CLI guidance can undo MCP preference.
- D6 (derived): preserve compatibility and explicitly track remaining exceptions; a generic argv gateway is insufficient.
- Rejected: always cheapest/largest, silent provider substitution, blanket shell bans, or protocol tests as behavioral proof.

A model inventory observation records provider/host, source, observation time, exact model IDs and
known capabilities. Unknown access/capability/cost remains unknown. A selection plan is an
agent-authored proposal tied to an assignment revision and inventory. Requested selection is what
creation receives; observed selection comes from the actual provider session. A native execution
route preserves host policy. A CLI exception explains why a named MCP operation cannot currently
serve the task; it grants no additional authority.

## Current source and gaps

| Source | Existing behavior | Extension |
| --- | --- | --- |
| providers/operations.py; runtime/task_schema.py | Optional model string; preserve-host-default | Difficulty assessment, inventory and selection plan |
| providers/contracts.py; providers/codex.py; providers/claude_sdk.py | Requested/actual model and creation mismatch checks | Link the existing checks to the selected plan |
| runtime/task_schema.py; runtime/tasks.py | Named memory, collaboration, provider, verification, Newsroom tools | Remaining workflow/ownership/learning/update/reporting operations |
| agents/store.py; providers/codex_delivery.py; providers/operations.py | Generated notifications contain CLI message lookup | Named MCP actions in all agent-facing instructions |
| install/projection.py; _assets/.agents/skills/plan-issues/SKILL.md and other bundled skills | MCP preference plus mandatory engine/skill CLI directions | Consistent operation map and evidenced exceptions |

These paths are relative to src/neurath. Current source must be reread before implementation.
MCP here describes the agent-facing control interface. An internal provider CLI process or native
host executor is not, by itself, an agent-facing CLI regression.

## Model selection requirements

| ID | Contract |
| --- | --- |
| MP-01 | Before each authorized new provider/session, form a plan, including explicit inheritance of the host default. Do not create a session solely to discover models. |
| MP-02 | Assess ambiguity, change breadth, reasoning depth, failure impact, tools/modalities, context demand and verification strength. Record concise evidence, difficulty (routine/standard/complex), and confidence. No token-count-only or fixed numeric score gate. |
| MP-03 | Honor explicit model/provider, allowed providers, budget and latency constraints. Choose sufficient evidenced capability within those constraints; known cost/latency are secondary considerations. Unknown price is not zero. Planning does not authorize buying quota or a new data destination. |
| MP-04 | Record assignment digest/revision, inventory observation, provider, exact model ID or explicit inherit, supported reasoning setting, rationale, rejected alternatives, constraints and replan triggers. Do not guess cross-provider reasoning-setting equivalence. |
| MP-05 | If inventory is unavailable, expose that limitation. A verified compatible existing default may be inherited with uncertainty recorded. An unverifiable explicit choice or required capability returns a structured blocker before assignment; no invented model ID or silent substitution. |
| MP-06 | Validate the plan/request binding before creation. An uncertain retry keeps identical run key, plan and request; reconcile the recorded outcome first. A changed model requires a new plan revision and a separately reconciled authorized attempt. |
| MP-07 | Before substantive assignment, compare requested and provider-observed selection using existing adapter checks. Alias equivalence requires authoritative resolution. Missing/mismatched evidence blocks assignment and retains diagnostic session/run identity. |
| MP-08 | Replan on changed assignment, invalidated availability or evidenced capability failure. Ordinary resume/message delivery preserves selection. Do not switch or restart a live session just because a turn ends. Changes beyond existing constraints require user input. |

A bounded text edit with a direct diff check may be routine; a multi-module feature with established
tests may be standard; an ambiguous permission-boundary change may be complex. Short work can be
complex because of failure impact. The bands explain reasoning, not an objective model quality score.

Registered source tools: provider_models observes available model metadata without
creating a session; provider_plan validates and retains the agent-authored plan. The deterministic
runtime validates structure, constraints and bindings, not subjective difficulty or model quality.
provider_route consumes the plan reference and exact selection; provider_run persists that reference
beside the durable run. Stale/altered plans fail before creation. Plan IDs never represent caller identity.

### Inherited defaults and plan revalidation

inherit refers to the default the target provider/host will apply to this creation, not the
model used by a parent on another provider. The plan retains resolved_model_id (possibly unknown),
default_source and default_observation_revision. Resolve an exact ID before creation when possible.
Otherwise only the preparation stage of the same authorized session may proceed: obtain native
model metadata, check the original capability/cost/latency constraints, and bind a new plan revision
before substantive assignment. Do not create a separate discovery session. If preparation would
require a paid model call whose hard constraints cannot be established, return a blocker.

A plan becomes stale when its assignment, target provider/host, constraints, effective policy,
policy mapping revision, observed target default, or a known invalidating inventory fact changes. Recheck availability
immediately before a new creation. Elapsed time alone does not cancel an existing task or its plan.
Reading the recorded outcome under the same already accepted key is not a new creation. S2 covers
target-default resolution and changes; S3 covers invalidated policy mappings and elapsed-time-only
cases. The provider_plan selection and provider_run readback retain the three default fields above.

## MCP operation requirements

| ID | Contract |
| --- | --- |
| MC-01 | Map every agent-facing harness operation to a named MCP tool, native execution route or explicit exception. Cover policy, skills, phase/state/worktree, learning, updates/reporting, notifications and errors. Unmapped routine operations fail the migration audit. |
| MC-02 | If an equivalent named tool is exposed and preserves policy, use it. Its active instructions, notifications, prompts and next_action must name the MCP action rather than direct executable CLI use. Keep developer compatibility references separate. Generic agent(argv) or an arbitrary engine/shell gateway does not satisfy migration. |
| MC-03 | Add typed phase/state/evaluation and worktree actions over existing kernel APIs. Preserve native identity, exact-owner fencing, workflow revision, evaluator consumption and completion gates. No arbitrary module, Python expression, file write or caller-identity input. |
| MC-04 | Add typed learning/update/reporting actions with existing preview/consent/recovery, privacy, exact contribution approval and uncertain-result handling. External submission is not implicitly approved by MCP. Where enforcement is incomplete, retain a native route or explicit migration gap. |
| MC-05 | CLI exceptions are limited to pre-install bootstrap, hooks/non-agent automation, missing/unexposed named operations, or inability to preserve host policy through MCP. Record operation, inventory evidence, reason, attempted path and recovery action. Convenience, old examples or denial do not justify a bypass. |
| MC-06 | Separate failure before acceptance from accepted/uncertain side effects. Recover from recorded outcome or relevant events; never repeat an uncertain mutation via CLI. Changing transport cannot bypass permission denial. |
| MC-07 | Preserve saved CLI/legacy MCP compatibility while removing their precedence from active agent instructions. Update source assets, manifest and package/install tests, then coordinate self-install. Do not edit projected skills by hand. |
| MC-08 | Fresh Codex and Claude natural-language scenarios must complete with zero unjustified CLI/legacy-argv calls for covered routine actions. Record inventories, actual calls, outcomes and exceptions privately. Unsupported cases remain explicit gaps. |

A named tool that prepares a native action has not executed it. The host must execute under its
policy and the operation must read back the result. A route still requiring the agent to assemble
Neurath CLI commands remains an exception and migration work. Source editing/testing shell commands
are repository development, outside the harness-operation metric.

Message transport follows the collaboration contract: unacknowledged peer messages remain eligible
for at-least-once redelivery with the same message ID and content. MC-06 prevents duplicate side-effect
execution through a fallback tool; it does not permanently freeze uncertain message delivery. Do not
add polling, heartbeat, a receiver-only model session, or a general task lifetime timeout.

## Proposed named operation surface

This section describes the target operation contract. The registered names in
[Task tools](task-tools.md) and each installed host's current schema define callable inputs. These names and core inputs define the
implementation boundary; the implementation must publish closed, versioned input/output schemas,
not accept JSON strings that deserialize into arbitrary state or CLI argv.

Every response uses the existing ok/operation/result or structured error envelope. Read operations
have no mutation authority. Writes require the current native caller and existing ownership,
revision and approval checks. A key identifies an identical request, never caller identity.
Targets may identify resources; actor/session/turn authority is derived only from native evidence.

| Proposed operation | Core structured input | Existing owner / effect and authority |
| --- | --- | --- |
| provider_models | provider; target worktree | Provider adapter; metadata observation and persistence, not a pure-read task. Records source, time, supported IDs and explicit unknowns without a model query. |
| provider_plan | assignment revision/digest; inventory observation ID; difficulty/evidence/confidence; selection; constraints; rationale; key | New planning contract; validate and persist the proposal. Selection contains provider, model ID or inherit and supported reasoning setting. Caller-supplied descriptions cannot establish model availability. |
| session_inspect, turn_inspect | none | StateHandle/state_cli; current caller only, read-only kernel and turn diagnostics. Keep session_status as installation/policy/ownership summary. |
| session_recover | expected session revision | Current root; recover only from authoritative native new-turn evidence. No invented turn or foreign-session attachment. |
| workflow_start | workflow_id; registered kind; goal; schema-validated initial state; key | Existing workflow service; normal owner and workflow-specific schema. |
| workflow_advance, workflow_finalize | workflow_id; expected_revision; schema-validated transition; key; final status for finalize | Existing transition and terminal gates. No arbitrary payload patch or self-certified completion. |
| phase_start | workflow_id; registered skill; run_id; north_star; key | PhaseRunner.initialize; native evaluator registration and all existing prerequisites. |
| phase_current | workflow_id | PhaseRunner.current; read-only requirements and revision. |
| phase_complete, phase_finalize | workflow_id; expected_revision; phase_id/status/summary/evidence refs for complete; terminal_state for finalize; key | PhaseRunner; consume authoritative evidence and enforce terminal checks. An evidence ref is resolved and authenticated, not trusted as a string. |
| adaptive_read, adaptive_preflight | workflow_id (optional only for preflight) | Existing adaptive-control read/preflight; no state mutation. |
| adaptive_replace, adaptive_override_goal | workflow_id; expected_revision; closed AdaptiveControlState; key | Existing adaptive service; validate every typed section and source/goal revision. Goal override additionally requires current user intent evidence. |
| material_prepare | batch_id; closed MaterialActionKind; targets; typed expectations; optional workflow_id; key | Existing action preparation; authorize exact targets and bind expectations. Does not edit files or run a command. |
| material_read, material_resolve, material_abandon | read: current batch; others: batch_id, expected_revision, closed resolution or abandoned invocation reference, key | Existing material service. Resolve from actual host invocation and readback, not caller-supplied success. No arbitrary execution gateway. |
| worktree_inspect, worktree_claim, worktree_release | inspect/claim: none; release: expected claim revision/token reference | WorktreeRegistry; native cwd and exact actor, first-writer-wins claim and CAS release. No force takeover, PID-based ownership or caller-supplied actor. |
| delegation_prepare, delegation_assign | delegation_id; assignment; key; assign additionally discovered target reference and workflow_id | Existing delegation contract and state service. Preparation grants no direct-child lineage; assignment checks actual native lineage or the separate peer task contract. |
| evaluation_prepare, evaluation_read, evaluation_execute | workflow_id; typed adaptive state or prepared assignment reference; execute additionally criterion_id, closed evidence kind, registered test reference | Existing adaptive evaluation APIs. Execute preserves native execution policy; no arbitrary shell or invented evaluation receipt. |
| evaluation_report, evaluation_consume | delegation_id; key; report: verdict/summary/outcome reference/findings | Existing delegation report/consume. Only the genuine assigned evaluator can report; parent consumes authenticated independent evidence. |
| learning_status, learning_history, learning_pending, learning_defer | none; history: strategy_id; defer: reason and key | memory/learning.py; current native binding is implicit. No tool to set candidate/trial/active/reverted manually: observe/verified hooks and validated execution evidence own promotion and rollback. |
| releases_status, releases_check, releases_notice | none; check: force only with explicit refresh request | updates.py; check is a policy-controlled network/local-state operation and notice records consumption, neither is pure read. |
| releases_prepare, releases_choose, releases_apply, releases_recover | offer_id except recover; choose: closed decision plus native user-choice reference; stable request key | updates.py; exact preview/consent/version/digest and recovery gates. Preparation is not installation; apply cannot manufacture consent. |
| reporting_status, reporting_list, reporting_read | none; read: draft_id | reporting.py read methods; expose exact draft and status without publishing. |
| reporting_prepare | the existing eight closed report fields; privacy review assertion; key | Reporting.prepare; manifest/common-scope and semantic privacy checks. Privacy assertion is not publication approval. |
| reporting_consent, reporting_approve | decision; native user-choice reference; approve additionally exact draft_id | Existing consent/approve semantics; no approval inferred from historical memory or a model boolean. |
| reporting_submit, reporting_reconcile | draft_id; reconcile additionally exact issue URL; key | Existing fixed-destination submit/readback/reconcile; enforce common-report consent or exact contribution approval, owner/network policy and uncertain-send handling. Use a native route until MCP can enforce those constraints. |

Backing APIs are in _assets/scripts/agent_harness/state_cli.py, worktree_registry.py, state_handle.py,
_assets/scripts/skill_harness/phase_runner.py, memory/learning.py, updates.py and reporting.py.
This table is the minimum new operation set, not a license to omit other agent-facing operations:
C1 must map every remaining skill helper and generated instruction. Expose additional helpers only
as bounded named domain operations; unsupported ones remain explicit migration gaps.

Model plan/readback outputs retain plan_id/revision, assignment digest, inventory source/revision,
requested selection, observed selection (or unknown), validation status and blocker/replan reason.
The plan does not expire merely because an ordinary task runs for a long time; changed constraints,
assignment or invalidated inventory trigger revalidation. Provider-specific inventory discovery must
use a currently supported native adapter and may return unavailable; no fabricated universal API.

## Scenarios, coverage and test-first validation

| Scenario | Acceptance evidence | Requirements |
| --- | --- | --- |
| S1: routine and complex new assignments | Evidence-based difficulty and selection; model IDs differ only where justified | MP-01–04 |
| S2: fixed/unavailable model, unknown inventory, unsupported reasoning | Fixed choice preserved or blocker; explicit permitted inheritance; no invented capability | MP-03–05 |
| S3: stale plan, altered request, actual mismatch, alias | No substantive assignment without verified binding; authoritative alias resolution | MP-06–07 |
| S4: quota failure/changed scope after uncertain create | Earlier outcome reconciled; no unexamined duplicate run | MP-06–08 |
| S5: recall, discovery/send/read/reply, Newsroom, status | Named MCP calls including notification/error recovery | MC-01–02, MC-08 |
| S6: phase transition, claim conflict, learning rollback, update/report preparation | Typed state and unchanged authority; native route or explicit gap | MC-03–05 |
| S7: unavailable MCP, restricted policy, interrupted accepted mutation | Evidenced exception; no privilege expansion or duplicate mutation | MC-05–06 |
| S8: saved legacy call and fresh installed host | Backward compatibility, correct new tool selection, existing settings preserved | MC-07–08 |

Start with failing plan/schema/binding tests, then adapter fixtures, instruction regressions and
install fixtures. Run applicable S1–S8 on actual Codex and Claude hosts. Protocol behavior, installation,
agent tool choice and model task quality are separate evidence. Planner rationale is not its own
quality oracle. Existing suite success does not establish these new acceptance results.

## Work items, ownership and continuation

These are local implementation drafts; no GitHub objects are created. Each child targets one
session and at most five primary files. Split any item exceeding 300 new or 200 changed code lines,
or spanning independently deliverable kernel domains. Contract changes precede adapter changes.

| Item | Scope / first failing test | Dependencies |
| --- | --- | --- |
| M1 | Inventory/selection contracts; invalid/stale plan rejection | none |
| M2 | Codex inventory and requested/actual binding fixture | M1 |
| M3 | Claude inventory and requested/actual binding fixture | M1; reuse M2 contract pattern |
| M4 | Named model tools and route/run plan linkage; request/key mismatch tests | M2, M3; execution-owner integration |
| C1 | Full operation/instruction inventory; notification MCP regression | none; notification-owner coordination |
| C2 | Typed phase/ownership actions; identity/fencing/evaluator failures | C1; split per kernel domain if needed |
| C3 | Typed learning actions; trial/promotion/rollback authority | C2 |
| C4 | Typed update actions; exact consent and interrupted recovery | C1 |
| C5 | Typed reporting actions; privacy, exact approval and uncertain submission | C1 |
| C6 | Bundled instruction migration; obsolete CLI guidance failures | C2–C5, M4 |
| V1 | Distribution/install checks and fresh-host S1–S8 | C6 |

Each child has three acceptance obligations: implement its linked requirements, demonstrate its
named failing/passing regression, and retain limitations. M1 covers MP-01–06; M2/M3 MP-05–07;
M4 MP-06–08; C1 MC-01–02; C2 MC-03; C3–C5 MC-04–06; C6 MC-02/07; V1 MC-07–08 and S1–S8.

M2/M3 can run independently after M1; C3/C4/C5 after their prerequisites. Shared runtime/task_schema.py,
runtime/tasks.py, providers/operations.py, policy, manifest and self-install have a single integration
writer. Delivery/ACK/retry, permission inheritance and process lifetime belong to concurrent delivery
work; exchange exact contracts/patches before touching these files. Critical paths are
M1 → M2/M3 → M4 → C6 → V1 and C1 → C2–C5 → C6 → V1; this is not an all-parallel plan.

Resume from this file and its linked source/reference documents. Resolve provider-specific inventory
adapters from current native capabilities; implement the named operation surface above over existing typed APIs. No fixed price
table, commercial ranking, implementation completion or native acceptance is established here.

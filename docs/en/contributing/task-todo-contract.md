# Measurable tasks and the authoritative TODO list

**English** · [한국어](../../ko/contributing/task-todo-contract.md)

[Architecture](architecture.md) · [Runtime lifecycle](runtime-lifecycle.md)

Status: source implementation exists for the named task operations, SQLite-backed persistence,
native projection and task-aware Stop admission. Native host activation and end-to-end acceptance
remain pending; this document does not certify them.

## Decisions and terminology

A **task** is a unit of an instruction whose outcome can be decided from stated acceptance
conditions and evidence. Instructions include native user prompts, tickets, and specifications.
The agent performs semantic decomposition; the kernel preserves and validates the resulting
records. A **TODO list** is a query of those canonical task records, not a second editable store.
Existing phase workflows implement tasks and provide evidence; finishing one phase or workflow
does not by itself finish the originating request.

The current source operation surface is `task_define`, `task_list`, `task_start` and
`task_resolve`. These operations observe the canonical task records and native TODO projection;
their source presence does not prove that a particular host exposes or has activated them.

| Requirement | Required behavior |
| --- | --- |
| T01 Measurable definition | Each task records its source, scope, acceptance conditions and evidence requirements. A vague activity label alone is insufficient. |
| T02 Source coverage | Preserve prompt, ticket and specification references and revisions; connect derived work to the instruction that requires it. |
| T03 Durable identity | Named MCP definition operations allocate unique task IDs with idempotent replay. Store tasks in the canonical process kernel and reject caller identity injection. |
| T04 Query | Named MCP operations return task records, current statuses, dependencies, evidence and list revision without reconstructing them from prose or UI. |
| T05 Visibility | Project the current list through the host's native TODO visualization tool after definition, addition and transition. The UI cannot write completion authority back into the kernel. Unavailable native visualization must be reported, not simulated as successful publication. |
| T06 Evidence-backed resolution | Accept succeeded, failed or invalidated only after validating the task's required evidence and exact current revision. A checkpoint or a bare completion assertion is insufficient. |
| T07 Stop gate | Reject the agent's normal Stop while any task is nonterminal. A completed side question, elapsed time or an exhausted continuation budget cannot waive this gate. |
| T08 Dynamic expansion | Add tasks during execution without replacing the list or renumbering existing IDs. New tasks immediately participate in visibility and Stop admission. |
| T09 Unified persistence | Store mutable runtime state in the common project's SQLite database. Do not maintain separate JSON files as competing runtime authorities. |

## SQLite storage decision

SQLite is the durable store for tasks, sessions, workflows, ownership, messages, provider runs,
model inventories, evidence, verification obligations and runtime checkpoints. Scope records by
project, worktree, session and actor as appropriate. The typed kernel continues to validate
authority and transitions; changing the storage engine does not weaken those checks.

Related state changes commit in one transaction. Task additions and Stop admission must observe
the same committed revision. Preserve idempotency keys, ownership fences and evidence provenance
through concurrent requests, interruption and restart. JSON may remain a serialization format
inside database records and on external interfaces; it is not a separate local runtime store.
Versioned project configuration, installation manifests and user deliverables retain their
required file formats because they are external inputs or outputs rather than runtime truth.

Migrate existing runtime records transactionally and verify their identities, revisions and
references before switching readers. Record the migration version and prevent legacy writers
from reviving a second authority. Preserve recovery material until migration is verified;
never interpret missing, corrupt or partially migrated state as completed work.
The runtime currently detects changes from the legacy path while the guarded writer cutover is
still an acceptance requirement. Do not claim that legacy writers are permanently excluded until
that cutover is independently verified.

Model catalog observations are cached per native issuer and provider and reused across turns and
worktrees. Refresh requires an explicit request or concrete stale catalog evidence; a new
assignment or target may require a new plan and target/policy admission without requiring fresh
catalog discovery. Bulk collaboration sends use structured `messages`, commit atomically and
fan out to exact recipients; queued or submitted is not receipt or task completion.

## State and evidence

Nonterminal states are `pending` and `in_progress`. Terminal states are `succeeded`, `failed`
and `invalidated`. Preserve terminal records and their evidence. Failure requires the observed
unsuccessful outcome and reason; invalidation requires the source decision or duplicate/supersession
evidence that made the work unnecessary. Neither state may be used merely to escape the Stop gate.
An invalidated duplicate references the work or result that already covers its acceptance.

Each definition includes a concise title, source references, acceptance conditions, expected
evidence kinds and optional dependency IDs. Server-issued IDs and mutation keys provide stable
replay. Store task and list revisions; stale transitions or changed reuse of a key must fail
without partially applying a batch. Reject missing dependencies and cycles. A new instruction
extends the live list; answering a side question does not replace earlier work.

Resolution references existing authoritative workflow results, executed verification records,
consumed independent reviews or authenticated source/user decisions, according to the task's
acceptance contract. Validate the evidence's owner, subject, source basis and outcome. UI status,
agent-report metadata and prepared evidence remain distinct from accepted evidence.

All-terminal means the session's work is settled, not necessarily successful. The final report
separates successful, failed and invalidated tasks. Explicit user pause or cancellation remains
host authority; it preserves unfinished tasks and must never synthesize success.

## Atomic closure and native projection

Task addition, resolution and Stop admission use the same canonical process revision. The
final Stop transaction rechecks the current list, preventing an all-terminal snapshot from
closing a session after another task was added. Preserve this invariant across turns, native
notifications, interruption, compaction and restart. A missing or unreadable task record is
not an empty completed list.

Native TODO output includes stable task IDs and the list revision. Publish pending and active
work faithfully, and show terminal failures and invalidations distinctly even if the native
tool offers only a generic completed state. Record publication separately from task resolution.
A stale or unavailable UI never changes task truth or grants Stop permission.

## Implementation order and acceptance

1. Kernel task records, IDs, revisions, append/transition invariants and backward-compatible loading.
2. Named bulk definition/query/resolution operations and adapters to existing evidence producers.
3. Native TODO projection and task-aware Stop admission, including explicit host interruption.
4. Intake and autopilot integration: classify already covered work, append required self-repairs,
   preserve work through side questions, and connect phase/evaluator outcomes to exact tasks.
5. Paired documentation, packaging/install checks and actual Codex/Claude native acceptance.

Regression scenarios cover duplicate definition replay, foreign/stale evidence, partial failure,
invalidated duplicates, additions during work and during Stop, retained IDs/history after restart,
one task succeeding while another remains active, UI drift, repeated Stop, and explicit user pause.
Existing fixes for catalog reuse, bulk messages, verifier concurrency, release finalization and
parametrized verification remain separate measurable tasks in the same original work scope.

## Requirement and acceptance traceability

| Functional ID | Decision | Acceptance ID and observable outcome |
| --- | --- | --- |
| FR-001 | T01 | SC-001: the kernel rejects a task without acceptance conditions or required evidence kinds. |
| FR-002 | T02 | SC-002: task readback retains the exact prompt, ticket or specification source and revision. |
| FR-003 | T03 | SC-003: replaying an identical definition returns the same IDs; changed input under the key is rejected. |
| FR-004 | T04 | SC-004: reopening the canonical state returns the same task IDs, statuses, evidence and list revision. |
| FR-005 | T05 | SC-005: native TODO publication shows every current task and its revision; missing capability is an explicit unavailable result. |
| FR-006 | T06 | SC-006: unresolved, foreign or mismatched evidence cannot terminalize a task; accepted terminal records retain their evidence. |
| FR-007 | T07 | SC-007: repeated normal Stop is rejected while one task remains pending, even after a side question was answered. |
| FR-008 | T08 | SC-008: a task added between Stop inspection and commit invalidates that close; prior task IDs and terminal history remain intact. |
| FR-009 | T09 | SC-009: migrated runtime records retain identities, revisions and references; concurrent updates and interrupted migration cannot produce competing JSON and SQLite authorities. |

The kernel slice owns FR-001 through FR-004 and FR-008; the evidence adapter owns FR-006;
the host integration slice owns FR-005 and FR-007. Kernel schema is the shared dependency and
must land before adapters. Native TODO publication and terminal evidence have separate acceptance
records. This contract is the durable decision log and resume source; no separate ADR is needed
because it already records the explicit user decision and its state/visibility trade-off.

### Task result reports

For success or failure, `task_resolve` receives the exact bound terminal
`workflow:<id>:<revision>` and a native-root `assessment`. The assessment contains
a summary and one entry per acceptance condition: `condition`, `outcome`
(`met` or `unmet`), `explanation` and the exact workflow `reference`.
Success requires all conditions met; failure requires at least one unmet condition.
The service validates ownership, the original task/workflow binding, revisions and
coverage. Existing phase and evaluator review requirements still apply to the workflow.

An optional `delegation:<consumed-id>` adds independent task review. When supplied,
the service checks the consumed native child report, exact task/workflow binding
and agreement with the root assessment. Ordinary task resolution needs no extra reviewer.

Invalidation can use a root `decision` bound to an authenticated current or retained
native prompt reference and digest. The decision records its disposition and reason;
duplicate or superseded work also requires covering source or completed-workflow references.
The existing consumed independent decision route remains supported.

The service stores one compact result report as an artifact and references it from
the task. Workflow evidence and logs are reused by reference. The report's assurance
is `agent-assessment`; recording it does not claim independent certification.

New native root workflows require a pending or active task with the same workflow
ID and goal before they can start. A rejected start leaves its request key reusable
after task definition. Existing workflows and direct-child execution retain their
current resume and evaluator rules.

Sessions without a defined task ledger retain their existing Stop rules. Workflow
status cannot manufacture an all-terminal task list. Once a ledger exists, every
nonterminal task blocks normal Stop, including tasks appended during execution.

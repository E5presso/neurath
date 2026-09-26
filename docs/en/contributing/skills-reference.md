<!-- updated: 2026-09-14; synced_from: 243400e58ca74c7fd79bcdd86b488953fa743b97 -->

# Choose a procedure that serves the user's outcome

[한국어](../../ko/contributing/skills-reference.md) · [Contributor start](index.md)

A skill is a reusable procedure for an agent. It tells the agent how to carry out a class of work and, where a phase contract exists, what evidence must be recorded along the way. A skill does not replace the user's goal or authorize every action its procedure can describe.

In the hypothetical saved-filter investigation, `debug` can structure reproduction and diagnosis. `review-code` can inspect the eventual change, and `qa` can verify the browser-visible result, API behavior, and retained data. The purpose is still to make the saved selection survive refresh with the existing behavior preserved. Completing a skill's step is useful only insofar as it advances that outcome.

## Use public names and edit owned sources

The installed catalog contains 31 public skills: 29 have phase contracts; `explain-code` and `graphify` are supporting skills without one. Public names are mapped from source identifiers. For example, users invoke `debug` while the source directory and contract identify `investigate`. An installation prefix changes invocation spelling, not the internal skill identity or phase IDs.

The editable originals live under [src/neurath/_assets/.agents/skills/](../../../src/neurath/_assets/.agents/skills/). Installed `.agents/skills` and `.neurath/rules` are projections. Change the original asset and update its generated manifest in an authorized implementation change. Installation, package execution, and real-host activation remain separate validation work; merely editing the procedure does not prove that an already-open host loaded it.

The catalog below starts from the work the agent needs to do. Read the selected skill's full current instructions and the target project's bindings before execution.

| Skill | Work it serves | Source ID | Phases | Terminal states |
| --- | --- | --- | --- | --- |
| `review-spec` | Check the implementation against its specification. | `audit-spec` | 1 | `completed`, `blocked`, `failed` |
| `qa` | Verify user-visible behavior, API evidence, and persistence. | `automate-qa` | 3 | `qa-complete`, `blocked`, `failed` |
| `autopilot` | Coordinate authorized issue work and dependencies. | `autopilot` | 7 | `merged`, `failed`, `skipped`, `blocked` |
| `checkpoint` | Retain the current work and next steps. | `checkpoint` | 1 | `completed`, `blocked`, `failed` |
| `commit` | Review and commit the authorized file scope. | `commit` | 3 | `committed`, `failed`, `blocked` |
| `create-pr` | Prepare and create an authorized pull request. | `create-pr` | 3 | `pr-created`, `blocked`, `failed` |
| `create-issue` | Turn requirements into actionable issues. | `create-ticket` | 4 | `created`, `blocked`, `failed` |
| `create-worktree` | Create an isolated checkout for authorized work. | `create-worktree` | 1 | `completed`, `blocked`, `failed` |
| `audit-deps` | Review dependency safety, licenses, and freshness. | `dependency-audit` | 1 | `completed`, `blocked`, `failed` |
| `test-harness` | Evaluate harness behavior against explicit scenarios. | `evaluate-harness` | 3 | `evaluated`, `blocked`, `failed` |
| `explain-code` | Explain a relevant source path or behavior. | `explain-code` | — | Supporting |
| `design-ui` | Explore interface directions before selection. | `explore-ui` | 4 | `direction-selected`, `needs-more-exploration`, `blocked`, `failed` |
| `finish-session` | Reconcile current work before session closure. | `finish-session` | 6 | `finished`, `failed`, `blocked` |
| `graphify` | Explore source and knowledge relationships. | `graphify` | — | Supporting |
| `implement-ui` | Implement an agreed interface direction. | `implement-ui` | 1 | `implemented`, `blocked`, `failed` |
| `debug` | Reproduce a failure and establish its cause. | `investigate` | 1 | `completed`, `blocked`, `failed` |
| `watch-pr` | Follow an authorized PR through relevant changes. | `monitor-pr` | 4 | `mergeable-clean`, `merged`, `failed`, `blocked` |
| `optimize-harness` | Improve harness execution using evidence. | `optimize-harness` | 3 | `optimized`, `blocked`, `failed` |
| `plan` | Plan bounded issue work and dependencies. | `plan-issues` | 8 | `persisted`, `blocked` |
| `review-pr` | Review a pull request and its acceptance. | `pr-review` | 1 | `completed`, `blocked`, `failed` |
| `implement-issue` | Carry an issue through implementation and checks. | `process-ticket` | 9 | `merged`, `mergeable-clean`, `failed`, `skipped`, `blocked` |
| `memory-to-rules` | Propose reviewed durable guidance from memory. | `promote-memory` | 1 | `completed`, `blocked`, `failed` |
| `review-code` | Inspect changes for actionable defects. | `review-code` | 1 | `completed`, `blocked`, `failed` |
| `review-ui` | Review the implemented user interface. | `review-ui` | 2 | `review-ready`, `accepted`, `revision-requested`, `blocked`, `failed` |
| `sync-design` | Reconcile implementation with design sources. | `sync-design` | 1 | `synced`, `no-change`, `blocked`, `failed` |
| `dev-docs` | Update contributor and developer documentation. | `sync-dev-docs` | 1 | `completed`, `blocked`, `failed` |
| `sync-docs` | Coordinate documentation synchronization. | `sync-docs` | 6 | `synced`, `blocked`, `failed` |
| `user-docs` | Update reader-facing usage documentation. | `sync-user-docs` | 1 | `completed`, `blocked`, `failed` |
| `pr-feedback` | Triage and address pull-request feedback. | `triage-comments` | 1 | `completed`, `blocked`, `failed` |
| `update-deps` | Apply and verify authorized dependency updates. | `update-dependencies` | 1 | `completed`, `blocked`, `failed` |
| `update-status` | Reflect verified progress in project status. | `update-project-status` | 1 | `completed`, `blocked`, `failed` |

## Record progress only when its evidence exists

An explicit phase contract is a stateful procedure. `phase_start` binds a `workflow_id`, public/source skill identity as required by the runtime, `run_id`, and the `north_star` outcome. `phase_current` returns the current phase and revision. Reading the skill or saying that a phase passed does not advance it.

`phase_evidence_prepare` creates an immutable evidence reference for the current phase and revision. Evidence labels come from that skill's contract. Its notes distinguish agent reports from observed source or execution evidence. `phase_complete` uses the exact expected revision and evidence reference. `phase_finalize` records the allowed terminal state when a separate finalization is required. An operational final phase may finalize atomically with `terminal_state`; do not finalize it twice.

For `finish-session`, a clean Git tree lets `stage_scope` and `commit` be skipped. Prepare a fresh source-read `clean_tree` reference at each phase revision; it proves that the index and working tree are empty and binds the unchanged HEAD across both skips. Changed trees still require `staged_files` and `commit_sha` on the completed path. The later `push_readback` still checks the exact remote HEAD.

For the filter example, a QA phase may need the actual browser observation, API/network result, and persistence readback. A screenshot of the selected filter before refresh cannot substitute for evidence that it survives a fresh load. A test name in a plan cannot substitute for its observed execution result.

Contracts have different semantics. Operational procedures project bounded actions such as preparing a commit or checkpoint. Semantic/adaptive procedures can require independent evaluation and an exact candidate binding. The latter must have the right evaluator role and authenticated report consumption; an arbitrary peer's positive comment does not satisfy that contract. Changed source, intent, owner, or workflow revisions can invalidate old candidate evidence.

## Keep the procedure inside the authorized scope

A procedure can contain issue creation, push, PR publication, cleanup, or promotion steps. The current user request and project instructions determine whether those actions are authorized. If a step lacks its prerequisite, preserve the work and report the concrete missing condition. Do not invent a base branch, remote ref, verification command, permission mode, or acceptance criterion to make a phase advance.

`worktree_isolation` verifies a distinct issue/root topology and a clean root, then claims; it does not create or switch checkouts. Cleanup requires actual branch/ref observations and the stored ownership/cleanup fences. Similarly, `memory-to-rules` can propose a lesson without editing rules; approved durable promotion is a separate repository change.

Ordinary task completion follows the task ledger. TODO display, a checkpoint, learned guidance, and a free-standing review are not additional ordinary completion votes. Explicit phase/review contracts still apply when chosen for authorized work. A failed attempt, a side question, or a budget limit does not cancel the original filter requirement.

`review-pr` publishes its comment and exact-head `ai-review` status only after it verifies that the repository's required `.github/workflows/ai-review.yml` approval automation exists and is active. A missing, disabled, or unreadable workflow is an unsupported prerequisite and produces no publication side effect. The procedure does not infer a status-only repository policy or invent an approving reviewer.

## Inspect a contract and a failure at their source

The source/public mapping is [src/neurath/skill_names.py](../../../src/neurath/skill_names.py); projection is in [src/neurath/install/projection.py](../../../src/neurath/install/projection.py). Contracts are collected in [src/neurath/_assets/.agents/skills/contracts.json](../../../src/neurath/_assets/.agents/skills/contracts.json); each skill's instructions and any phase files are in its own directory. The table records phase count and allowed terminal states to help locate the right procedure; exact labels and evidence patterns belong to the selected contract.

Named phase tools are defined in [src/neurath/runtime/workflow_tasks.py](../../../src/neurath/runtime/workflow_tasks.py). Current discovery uses `phase_start`, `phase_complete`, and `phase_finalize`; older `workflow_start`, `workflow_advance`, and `workflow_finalize` names are saved-call compatibility. They are not a second procedure to run.

Relevant checks live in [tests/runtime/skill_harness/](../../../tests/runtime/skill_harness/) and [tests/runtime/agent_harness/test_workflow_terminal_admission.py](../../../tests/runtime/agent_harness/test_workflow_terminal_admission.py). They validate declared contracts and transition admission. To validate a real result, still inspect what the agent changed, the relevant project checks, and any required native/UI evidence.
## Named input reference

The tables below are the current named-tool input contract. Nested required fields are required when their parent object or array item is supplied. Schema acceptance is only the first check; native identity, ownership, source, revision, and operation-specific prerequisites still apply. The host supplies `_neurath_binding`; do not synthesize it.

Every response has `ok` and `operation`. A successful call carries its canonical `result`; a failure carries `error.code`, `error.message`, `error.state`, `error.retryable`, and `error.next_action`. An `ok` envelope establishes the stated operation only, not the user goal. Preserve returned IDs and revisions for dependent calls.

### `phase_start`

| Field | Presence / default | Type and limits |
| --- | --- | --- |
| `workflow_id` | required | text; 1–256 characters |
| `key` | required | text; 1–512 characters |
| `skill` | required | text; 1–128 characters |
| `run_id` | required | text; 1–256 characters |
| `north_star` | required | text; 1–16000 characters |

### `phase_current`

| Field | Presence / default | Type and limits |
| --- | --- | --- |
| `workflow_id` | required | text; 1–256 characters |

### `phase_evidence_prepare`

| Field | Presence / default | Type and limits |
| --- | --- | --- |
| `workflow_id` | required | text; 1–256 characters |
| `expected_revision` | required | integer; 0–9007199254740991 |
| `labels` | optional; default `[]` | array; 0–32 items; text; 1–16000 characters |
| `notes` | optional; default `[]` | array; 0–128 items |
| `notes[].label` | required | text; 1–128 characters |
| `notes[].text` | required | text; 1–16000 characters |
| `key` | required | text; 1–512 characters |

### `phase_complete`

| Field | Presence / default | Type and limits |
| --- | --- | --- |
| `workflow_id` | required | text; 1–256 characters |
| `expected_revision` | required | integer; 0–9007199254740991 |
| `key` | required | text; 1–512 characters |
| `phase_id` | required | integer; 0–1000 |
| `status` | required | text: `"completed"`, `"skipped"`, `"failed"`, `"blocked"` |
| `summary` | required | text; 1–16000 characters |
| `reason` | optional; default `""` | text; 0–16000 characters |
| `terminal_state` | optional; default `""` | text; 0–128 characters |
| `evidence_refs` | optional; default `[]` | array; 0–32 items; text; 1–16000 characters |

### `phase_finalize`

| Field | Presence / default | Type and limits |
| --- | --- | --- |
| `workflow_id` | required | text; 1–256 characters |
| `expected_revision` | required | integer; 0–9007199254740991 |
| `key` | required | text; 1–512 characters |
| `terminal_state` | required | text; 1–128 characters |

### `delegation_assign`

| Field | Presence / default | Type and limits |
| --- | --- | --- |
| `workflow_id` | required | text; 1–256 characters |
| `delegation_id` | required | text; 1–128 characters |
| `assignment` | required | text; 1–8192 characters |
| `target` | required | text; 1–512 characters |
| `key` | required | text; 1–512 characters |

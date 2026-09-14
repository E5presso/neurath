<!-- date: 2026-09-14; synced_from: 655c8768709e59b5e5012bab0adc4d888e3e7fa5 + current working-tree facts -->

[한국어](../../ko/contributing/skills-reference.md)

# Match a procedure to the requested result

A skill describes how an agent handles a particular kind of work. The user's outcome and constraints select it; the public name is a stable handle for contributors and explicit requests. Installation exposes 31 public skills. Of these, 29 have phase contracts; `explain-code` and `graphify` are support skills without phase contracts.

## Public names and implementation identifiers

Use the public name in user-facing instructions. Source directories and internal contracts retain the identifiers below. A configured installation prefix is applied to the public name: `neurath-` makes `debug` available as `neurath-debug`, while its internal identifier remains `investigate`.

| Work to perform | Public skill | Internal identifier |
| --- | --- | --- |
| audit requirements before implementation | `review-spec` | `audit-spec` |
| verify deployed interface/API/persisted result | `qa` | `automate-qa` |
| coordinate explicitly requested multiple issues | `autopilot` | `autopilot` |
| reversible WIP save | `checkpoint` | `checkpoint` |
| commit authorized verified change | `commit` | `commit` |
| authorized push and PR | `create-pr` | `create-pr` |
| create approved work items | `create-issue` | `create-ticket` |
| prepare isolated issue workspace | `create-worktree` | `create-worktree` |
| security/license/freshness/drift | `audit-deps` | `dependency-audit` |
| failure scenarios verify enforcement | `test-harness` | `evaluate-harness` |
| explain current source/test-backed behavior | `explain-code` | `explain-code` |
| explore design and obtain exact canvas choice | `design-ui` | `explore-ui` |
| authorized commit/push/graph update/claim release | `finish-session` | `finish-session` |
| explore code/document relationship graph | `graphify` | `graphify` |
| build exact approved node | `implement-ui` | `implement-ui` |
| reproduce and isolate defects | `debug` | `investigate` |
| observe PR changes | `watch-pr` | `monitor-pr` |
| reduce injected prompt preserving capability | `optimize-harness` | `optimize-harness` |
| clarify product decisions and decompose into docs/issues | `plan` | `plan-issues` |
| publish verified local review at exact PR head | `review-pr` | `pr-review` |
| implement one approved issue | `implement-issue` | `process-ticket` |
| review recurring private knowledge for approved project rule | `memory-to-rules` | `promote-memory` |
| find evidenced defects in changes | `review-code` | `review-code` |
| compare approved design and runtime for user judgment | `review-ui` | `review-ui` |
| repository tokens/component mappings into canvas | `sync-design` | `sync-design` |
| developer docs | `dev-docs` | `sync-dev-docs` |
| route documentation scope | `sync-docs` | `sync-docs` |
| approved implemented user behavior | `user-docs` | `sync-user-docs` |
| assess/respond to review comments | `pr-feedback` | `triage-comments` |
| controlled updates/checks | `update-deps` | `update-dependencies` |
| issue/project metadata | `update-status` | `update-project-status` |

The former standalone names `create-package`, `local-dev`, `onboard`, `refactor-code`, `impact-analysis`, `improve-coverage`, and `property-test` are not additional public skills. Select a current procedure from the intended work rather than assuming that an old name still names an installed entry.

## Inputs determine what counts as a result

For an implementation task, obtain the approved issue or specification, current checkout, relevant source, and real project checks. Keep the requested behavior and constraints as measurable task definitions. For a code review, inspect the exact changes and report source-backed defects. For a design task, retain the approved canvas or exact node reference so implementation and comparison have a fixed subject.

Delivery procedures need their own authorized scope. A reversible checkpoint, a local commit, a pushed branch, a published PR, and a completed session are distinct outputs. Selecting `create-pr` or `finish-session` does not manufacture authorization that the user has not given. Dependency work uses the project's actual dependency and check environment. QA verifies the deployed surface, API behavior, and persisted result relevant to the request.

The ordinary task ledger remains the completion authority when present. Native edits and checks use normal host tools. The visible TODO is a projection. A skill does not add a second mandatory per-criterion acceptance report, material batch, or independent task-review vote to every ordinary task.

## Execute an explicit phase contract

When a workflow explicitly requires stages or independent evaluation, use its phase contract:

1. Start it with `phase_start` and retain the returned workflow identity and revision.
2. Read `phase_current` for the current instructions, requirements, and interrupted state before a mutation whose freshness is uncertain.
3. Prepare evidence with `phase_evidence_prepare`. It validates required labels and current revisions and registers immutable evidence; an arbitrary artifact string does not satisfy the contract.
4. Submit the actual returned evidence to `phase_complete`. A described pass or a read instruction does not advance state.
5. Use `phase_finalize` when the contract requires separate finalization. If the last operational phase completed atomically with `terminal_state`, do not finalize it a second time.

Adaptive workflows require an actual independent evaluator before initialization. The evaluator reads the exact candidate artifact and evidence bound to goal, intent, source, and workflow revisions; the owner consumes the authenticated result with `evaluation_consume`. Changed content, ownership, or workflow state invalidates reused evidence. Peer-provider reports alone do not create direct-child evaluator authority.

The current public names are `phase_start`, `phase_complete`, and `phase_finalize`. Historical `workflow_start`, `workflow_advance`, and `workflow_finalize` calls remain saved-call compatibility routes but are not advertised to new callers. This compatibility does not add a routine shell gateway.

The scope of an investigation follows the original acceptance conditions. In particular, `test-harness` does not require unlimited inventory or evaluation generation merely to complete its process. A time or token limit guides the choice of useful next actions; it does not lower the user's goal. [Goal reflection](design-principles.md) supports that judgment without creating an additional phase or report. Other skills retain their own applicable iteration contracts.

## Modify a skill at its source

Installed `.agents/skills` entries and `.neurath/rules` are generated installation results. Change source assets under `src/neurath/_assets`, preserving the public-to-internal mapping and both host projections. A new prefix must remain consistent across installed paths and references; a name collision should preserve the user's existing skill and return a conflict.

After an execution-asset change, regenerate the manifest and perform the required validation, build, and self-install update as separate steps. For example:

```sh
uv run --locked python tools/build_manifest.py
uv run --locked python tools/check.py
uv run --locked python -m build
./setup --self
```

These commands are contributor execution references. A prose-only documentation edit does not require self-installation merely to make the text effective.

## Source and contract coverage

[Skill names](../../../src/neurath/skill_names.py) defines the public mapping; [the catalog](../../../src/neurath/_assets/scripts/skill_harness/harness_catalog.py), [phase runner](../../../src/neurath/_assets/scripts/skill_harness/phase_runner.py), and [skill state contract](../../../src/neurath/_assets/scripts/agent_harness/skill_state_contract.py) implement contract discovery and execution. [Phase-runner tests](../../../tests/runtime/skill_harness/test_phase_runner.py), [MCP guidance tests](../../../tests/test_mcp_guidance.py), and [installer tests](../../../tests/test_installer.py) cover the corresponding source and installed behavior.

For decision authority see [the task/TODO contract](task-todo-contract.md); for independent roles see [collaboration](collaboration-contract.md). [User skill guidance](../usage/skills.md) explains how to request the result in natural language.

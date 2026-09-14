<!-- date: 2026-09-13; synced_from: 655c8768709e59b5e5012bab0adc4d888e3e7fa5 + current working-tree facts -->

# Ask for work by its purpose

[한국어](../../ko/usage/skills.md)

Describe what you need in natural language. The agent selects the relevant skill and applies the project's instructions and checks. The public skill names below help identify a workflow; you do not need to memorize or invoke them as commands. An installation may add a prefix to avoid name collisions.

## Understand the problem before changing it

| Ask for | Skill | Result to inspect |
| --- | --- | --- |
| Explain how this part works using the current implementation and tests | `explain-code` | A source-backed explanation with relevant behavior and limits |
| Reproduce this defect and isolate its cause | `debug` | A reproducible failure, evidence for the cause, and the scope of a fix |
| Review these changes for defects | `review-code` | Evidenced findings tied to the inspected change |
| Review the requirements before implementation | `review-spec` | Gaps or conflicts that need resolution before the requirements can guide work |


## Plan and implement approved work

| Ask for | Skill | Result to inspect |
| --- | --- | --- |
| Turn this product goal into decisions and manageable work | `plan` | Product choices and a breakdown into documentation or issues |
| Create the work item we have approved | `create-issue` | The authorized issue and its stated scope |
| Implement this approved issue | `implement-issue` | The requested behavior and the checks performed for that issue |
| Coordinate these explicitly requested issues | `autopilot` | Progress and remaining work across the requested set |
| Prepare an isolated workspace for this issue | `create-worktree` | The worktree prepared for that issue and the relevant ownership status |

An implementation request for one issue does not implicitly expand into a multi-issue run. For parallel work and provider selection, see [Agents and shared work](agents.md).

## Work from a design through a deployed result

| Ask for | Skill | Result to inspect |
| --- | --- | --- |
| Explore interface designs and let me choose the exact canvas | `design-ui` | Design options and the specific canvas choice |
| Bring repository design tokens and component mappings into the canvas | `sync-design` | Canvas information aligned with the repository's design definitions |
| Implement this exact approved design node | `implement-ui` | The implementation corresponding to the selected node |
| Compare the approved design with the running interface | `review-ui` | Differences and runtime evidence for your judgment |
| Verify the deployed interface, API, and persisted result | `qa` | Observed behavior across the requested deployed flow |

For example, ask the agent to verify that saving a change in the deployed interface produces the expected API result and persists after a reload. A screenshot alone does not establish that the data was saved. The exact approved canvas or node keeps design implementation tied to your choice.

## Save, review, and deliver changes

| Ask for | Skill | Result to inspect |
| --- | --- | --- |
| Save a reversible work-in-progress checkpoint | `checkpoint` | A recoverable WIP save and handoff status |
| Commit the authorized and verified change | `commit` | A local commit covering the approved scope |
| Push these changes and create a pull request | `create-pr` | The authorized remote update and PR |
| Publish the verified local review of this PR | `review-pr` | A published review tied to the exact PR head inspected |
| Assess and respond to these review comments | `pr-feedback` | The disposition of the comments and authorized responses |
| Watch this pull request for changes | `watch-pr` | Observed PR changes relevant to the request |
| Update the issue or project status | `update-status` | The requested metadata changes |
| Finish this session with the specified delivery steps | `finish-session` | Authorized commit, push, graph update, and ownership release, as requested |

A checkpoint gives you a reversible save and a place to resume. When work is ready to deliver, specify whether you want a local commit, a push, or a pull request so the result matches your intended destination.

## Maintain documents, dependencies, and the harness

| Ask for | Skill | Result to inspect |
| --- | --- | --- |
| Determine which documentation needs updating | `sync-docs` | Documentation work routed to the appropriate scope |
| Update the developer documentation | `dev-docs` | Documentation of the developer-facing behavior and procedures |
| Document the approved, implemented user behavior | `user-docs` | User guidance that matches the implemented feature |
| Inspect dependency security, licenses, freshness, and drift | `audit-deps` | Findings covering the requested dependency risks |
| Update dependencies with controlled changes and checks | `update-deps` | The selected updates and their verification results |
| Check that the harness enforces its rules in failure scenarios | `test-harness` | The observed enforcement results and any gaps |
| Reduce injected harness instructions while preserving capability | `optimize-harness` | Reduced prompt content and evidence for retained behavior |
| Review recurring private knowledge for a project rule | `memory-to-rules` | A proposed rule reviewed for approved project use |
| Explore relationships among code and documentation | `graphify` | A relationship graph or explanation grounded in project material |

Use [project memory](memory.md) to recall the evidence behind a recurring lesson before proposing it as a project rule.

There are 31 current public skills in this guide. `create-package`, `local-dev`, `onboard`, `refactor-code`, `impact-analysis`, `improve-coverage`, and `property-test` are retired standalone names. Describe the result you want so the agent can use the current workflow.

Return to [Working with Neurath](index.md) for task tracking and completion evidence, or see [Project setup](profiles.md) to connect the documents and checks these skills use.

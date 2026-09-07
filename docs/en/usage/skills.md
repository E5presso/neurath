# Skill catalog
<!-- date: 2026-09-07; synced_from: source and documentation at 2456ae73ffaf818c04ea4419574218df36852805; English and Korean editions updated together -->

[Usage](index.md) · [Contributing](../contributing/index.md)


**English** · [한국어](../../ko/usage/skills.md)

Skills use unprefixed names in both hosts by default; an installation prefix changes the invocation
name, for example `/neurath-debug`. Start with `/debug` for a reproducible error, `/plan` for new
requirements, or `/review-code` for a change review. The [usage guide](index.md) explains what
to provide and how to assess the result. Clear names were retained, while unnecessarily long
or ambiguous names were simplified.

| Skill | Purpose |
| --- | --- |
| `plan` | Turn product requirements into a plan and issue structure |
| `review-spec` | Review specifications for gaps and contradictions before implementation |
| `create-issue` | Create GitHub issues for approved work |
| `implement-issue` | Implement and verify one approved issue |
| `autopilot` | Coordinate autonomous execution across multiple issues |
| `create-worktree` | Create an isolated working directory for issue work |
| `debug` | Reproduce errors and investigate their causes |
| `explain-code` | Explain code using the current source |
| `review-code` | Review code changes |
| `qa` | Verify behavior across actual clients, APIs, and persisted results |
| `design-ui` | Explore UI direction and obtain design approval before implementation |
| `sync-design` | Synchronize design tokens and component mappings |
| `implement-ui` | Implement an approved UI design |
| `review-ui` | Compare the approved design with the running interface |
| `checkpoint` | Save a reversible intermediate work checkpoint |
| `commit` | Commit verified changes |
| `create-pr` | Push a branch and create or update a PR |
| `review-pr` | Process review results for an exact PR version |
| `pr-feedback` | Assess and respond to PR review comments, accepting or disputing them |
| `watch-pr` | Observe changes in PR status |
| `update-status` | Update issue and project status |
| `finish-session` | Verify and close out a session |
| `sync-docs` | Classify and route documentation updates |
| `dev-docs` | Update developer documentation |
| `user-docs` | Update user documentation |
| `audit-deps` | Audit dependency security, licenses, and maintenance |
| `update-deps` | Update and verify dependencies |
| `test-harness` | Test actual harness enforcement with failure scenarios |
| `optimize-harness` | Refine instructions and prompts while preserving behavior |
| `memory-to-rules` | Turn repeatedly confirmed personal working knowledge into project rules |
| `graphify` | Explore code and documentation relationships through a knowledge graph |

## Renamed skills

| Previous name | Current name |
| --- | --- |
| `audit-spec` | `review-spec` |
| `automate-qa` | `qa` |
| `create-ticket` | `create-issue` |
| `dependency-audit` | `audit-deps` |
| `evaluate-harness` | `test-harness` |
| `explore-ui` | `design-ui` |
| `investigate` | `debug` |
| `monitor-pr` | `watch-pr` |
| `plan-issues` | `plan` |
| `pr-review` | `review-pr` |
| `process-ticket` | `implement-issue` |
| `promote-memory` | `memory-to-rules` |
| `sync-dev-docs` | `dev-docs` |
| `sync-user-docs` | `user-docs` |
| `triage-comments` | `pr-feedback` |
| `update-dependencies` | `update-deps` |
| `update-project-status` | `update-status` |

Updating an installation removes old managed paths. User skills with conflicting names and
manually edited managed files are not overwritten. Internal contract identifiers remain stable
so ongoing work records can still be read. Engine commands use the skill body's built-in contract
identifier, labeled `내장 계약`; scripts can use the current name, as in
`.neurath/run skill watch-pr <script>`.

`create-package`, `local-dev`, `onboard`, `refactor-code`, `impact-analysis`,
`improve-coverage`, and `property-test` are no longer standalone skills. Shared instructions
cover general implementation and testing principles. The design harness and QA verification
procedures remain available.

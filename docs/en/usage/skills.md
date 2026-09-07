# Skill catalog
<!-- date: 2026-09-07; synced_from: source and documentation at e1487a1718056b37b999d1343a1007b7e25f5c8c; English and Korean editions updated together -->

[Usage](index.md) · [Contributing](../contributing/index.md)


**English** · [한국어](../../ko/usage/skills.md)

The agent selects skills from your task's purpose, evidence, and authorization. Describe the
outcome in ordinary language; you do not need to invoke a skill or memorize its name.
For example, “Reproduce and fix this error” leads to debugging, and “Review this change”
leads to code review. This catalog explains the procedures available to the agent.

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

Installation naming and compatibility details are in the [skill execution reference](../contributing/skills-reference.md).

# Skill execution and compatibility reference

**English** · [한국어](../../ko/contributing/skills-reference.md)

<!-- date: 2026-09-07; synced_from: source and documentation at e1487a1718056b37b999d1343a1007b7e25f5c8c; English and Korean editions updated together -->

[Contributing](index.md) · [User skill catalog](../usage/skills.md)

These identifiers and commands are for agents executing an authorized task. Users provide goals; the agent selects and runs the appropriate skill. Default host names are unprefixed, such as `/debug`; an installation prefix can produce `/neurath-debug`.

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

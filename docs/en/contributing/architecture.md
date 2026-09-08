# Architecture and execution boundaries
<!-- date: 2026-09-07; synced_from: source and documentation at 2456ae73ffaf818c04ea4419574218df36852805; English and Korean editions updated together -->

[Usage](../usage/index.md) · [Contributing](index.md)


**English** · [한국어](../../ko/contributing/architecture.md)

Neurath is an independent harness kit with its own runtime, contracts, and distribution inventory.
It does not prescribe the target project's source, stack, documentation layout, branch names, or development environment.

The accepted [provider collaboration contract](collaboration-contract.md) defines provider-neutral
permission inheritance, process-owned supervision and at-least-once delivery. The accompanying
[model planning and MCP contract](model-planning-mcp.md) defines the next agent-facing control
surface. These contracts distinguish target requirements from the implementation below; app
membership and user observation are not prerequisites for the new collaboration design.

| Location | Responsibility |
| --- | --- |
| `src/neurath/_assets/scripts/agent_harness` | State, host identity, ownership, actions, and independent evaluation |
| `src/neurath/_assets/scripts/skill_harness` | Phase and evidence contracts, execution reports |
| `src/neurath/_assets/.agents` | Shared rules, 31 skills, and 29 execution contracts |
| `src/neurath/manifest.json` | SHA-256 inventory of all runtime code and assets |
| `src/neurath/install/` | Host placement, merging, conflict checks, journals, and recovery |
| `src/neurath/hosts/` | Native host calls, identity verification, and resume evidence |
| `src/neurath/memory/` | Shared project memory, reflection, and execution strategy learning and withdrawal |
| `src/neurath/agents/` | Peer messages, active Newsroom, and communication MCP bound to individual calls |
| `src/neurath/runtime/` | Verification commands configured by the target project |
| `tests/runtime` | Kit-owned regressions for state, contracts, and authority |

Public commands run through `python -I` in an isolated Python environment. A package named
`scripts` in the target project cannot shadow the bundled engine. Code and contracts come from
the distribution asset root; working content comes from the target Git worktree. State lives in
`.neurath/local/runs` and `.neurath/local/resources` under the shared Git control root.
Only `NEURATH_*` environment variables and `neurath.*` schemas are used. State from other
products is not inherited implicitly.

## Installation transactions

An installation plan binds target paths, the distribution fingerprint, selected hosts, and each
file's bytes, mode, and link before and after the change. Immediately before applying it, the
installer compares the plan against current files and applies it under a Git directory lock.
Files are written through temporary files and fsync/replace. A journal supports recovery after
failure or process interruption; concurrently edited user files are not overwritten.

Existing instructions, hook groups, permissions, and model settings are preserved. Uninstallation
restores the original content. Edits outside managed blocks in shared instructions and `.gitignore`
remain in their original positions; edits to managed blocks are rejected. Quick setup creates a
separate runtime environment for each distribution content fingerprint, preserving the runtime
used by existing projects. Only after target installation succeeds does the global command point
to the new environment. Previous environments remain available for restoration. Diagnostics also
compare the running distribution fingerprint with the target installation record.
An edited `.neurath/project.json` remains user-owned. Installation state and records containing
original file content stay in private local files and are not transmitted externally.

## Verification and authority

Of the 31 skills, `explain-code` and `graphify` are helpers without state-owning phase contracts;
the other 29 have phase and evidence contracts. Skill selection requires matching primary intent
and input authority. The `test-harness` kit regression matrix runs against kit development source,
while target project changes use that project's verification bindings. Product-specific profile
names and state namespaces are not supported.

General verification uses explicit argv, cwd, success conditions, and a timeout. A change to the
Git file fingerprint during execution fails verification even with exit code 0. Typed pytest
verification confirms that every requested leaf node actually passed; other passing tests or
skipped tests cannot substitute for it.

Distribution integrity, installation placement, test execution, independent review, and actual
host activation require separate evidence. `doctor` and static checkers cannot authenticate host
trust or parent–child relationships themselves. The runtime checks state access, concurrent edit
conflicts, workspace ownership, execution results for mutations, and completion conditions.
The [terminology guide](../terminology.md) maps these concepts to code identifiers.

## User input and execution state

Root `UserPromptSubmit` is the boundary for delivering user input. If state updates or memory
and message stores fail, input still reaches the agent with a `bookkeeping deferred` diagnostic.
That response does not imply a successful state update or permission to execute tools. Input from
another session is not imported into state or shared memory; tool and ownership checks still apply.

A new Codex `task_started` record provides evidence for recovering an unfinished previous turn.
A new turn is recognized even without a resume hook or when the user repeats the same sentence.
Previous tool calls whose results were not observed remain `unknown` or `blocked` and do not
complete a workflow. Additional input within the same turn is stored in memory with its accepted
revision and content digest.

## Project memory

Records with source information live in `.neurath/local/memory/project.sqlite3` under the shared
Git control root. They are separate from each session's state and ownership. SQLite transactions
handle concurrent writes and redelivery. Memory is shared across worktrees, while verification
contracts are read from the worktree where execution actually occurs.
[Memory and learning](../usage/memory.md) explains record selection and the execution strategy lifecycle.

## Newsroom

Articles store a title, body, author, and version; revisions and comments append immutable events.
The publication transaction queues headline notifications only for active participants. Participation
is bound to a native turn generation, and old notifications are discarded on deactivation, a new
turn, or expiry after 10 minutes. Checks compare directory entries with SessionKernel actor and
foreground state as well as the native process connection. SessionEnd leaves the logical session
resumable, so a separate connection-closure record is required. Host hooks inject up to 3,000 bytes
of headlines and lookup IDs; bodies require explicit lookup. Delivery records are separate from
read acknowledgements, and there is no separate runner that wakes agents.

The communication MCP server exposes no arbitrary Python, shell, or file operations. Native
PreToolUse binds a temporary token to the verified actor, turn, tool call, and exact request.
Changed requests, changed identities, expired tokens, and calls after closure are rejected.
PostToolUse closes the token; retries within the same call return the stored result. Claude
read-only workers receive only this additional communication tool. Codex registers only the new
communication tool with `tools.agent.approval_mode = "approve"`. When a native connection closes,
all communication tokens and cached results for that process are discarded. Installation preserves
existing Codex TOML and Claude MCP servers and permissions, stopping on conflicting user settings
with the same name. Uninstallation restores the original files exactly.

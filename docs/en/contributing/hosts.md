<!-- date: 2026-09-14; synced_from: 655c8768709e59b5e5012bab0adc4d888e3e7fa5 + current working-tree facts -->

[한국어](../../ko/contributing/hosts.md)

# Native host integration

Claude Code and Codex execute the project work. Neurath installs instructions, skills and event adapters that connect each host's actual session to the shared runtime. The adapter's most important job is to preserve native evidence: who called, which turn was active and whether a child was really created by the claimed parent.

## Installed surfaces

| Surface | Installation behavior |
| --- | --- |
| `AGENTS.md` | Add a marked managed block while preserving surrounding user text. |
| `.agents/skills/<name>` | Install shared skill projections used by Codex. |
| `.codex/hooks.json` | Merge command hook groups with existing hooks. |
| `CLAUDE.md` | Create a symlink to `AGENTS.md` when new; add an import block to an existing regular file. |
| `.claude/skills/<name>` | Link to `../../.agents/skills/<name>`. |
| `.claude/settings.json` | Merge Claude Code hook configuration. |

The installer does not set a user's model, sandbox or approval preferences. Existing inline hooks in `.codex/config.toml` are retained; a host may load both formats and warn, and diagnostics report the condition. Managed content changed by a user produces a conflict instead of being overwritten.

Neurath runs its own handlers sequentially within one event command. Other pre-existing hook groups retain the host's own scheduling behavior. The installed Codex `SessionEnd` command has a three-second timeout.

## Event responsibilities

| Native event | Runtime purpose |
| --- | --- |
| `SessionStart` | Establish or verify session recovery and load bounded project context. |
| `UserPromptSubmit` | Retain the new user instruction and establish the current request's native evidence. |
| `SubagentStart` | Observe a prospective child and verify its native relationship before granting authority. |
| `PreToolUse` | Admit the exact caller, current turn and tool input before a protected state or project action. |
| `PostToolUse` | Bind the actual result to the prepared invocation; record observations such as TODO submission outcome. |
| `PreCompact` | Preserve the supported bounded context before compaction. |
| `Stop`, `SubagentStop` | Check the applicable turn or child completion contract. |
| `SessionEnd` | Close the host connection without treating process exit as permanent domain-session termination. |

Claude Code additionally supplies `PostToolUseFailure` and `PermissionDenied`. Those events retain failure and refusal observations; a failure-shaped response must not be interpreted as a successful tool result.

For root `UserPromptSubmit`, a failure in internal recording or reconciliation still allows the user input through and adds a `prompt bookkeeping deferred` diagnostic. That diagnostic establishes no new execution or ownership authority; existing tool and ownership checks continue to apply. The behavior is implemented in [host hooks](../../../src/neurath/hosts/hooks.py) and covered by [prompt-delivery tests](../../../tests/test_prompt_delivery.py).

### Goal context on root events

Root prompt and tool-completion hooks can also supply a periodic reminder of task purpose and acceptance. The [runtime reminder contract](runtime-lifecycle.md) defines eligibility, cadence, and byte limits. This hook adds reference context while leaving task state and permissions unchanged; it does not ask the user or agent to start a reflection workflow.

## Native identity and direct children

A session or participant with `unattested` lineage cannot mutate execution state. The MCP binding associates a real connection with the native session and invocation. Do not manufacture `_neurath_binding`, native session IDs or actor identifiers in an example or recovery command.

For Codex, child verification compares the actual spawn result's path with the child transcript's parent and session metadata. `CODEX_THREAD_ID` is checked against the real child record. For Claude Code, a one-time reference to the parent's `Agent` call must be visible in the child transcript. Shell identity references are tied to the exact shell invocation. A copied, stale or reused reference provides no lineage authority.

Prepare delegation with `delegation_prepare` from the current parent foreground immediately before native spawn. After the real direct child exists, bind the assignment with `delegation_assign`. Late transcript registration may be checked again at the child's first state-tool call. Until verification succeeds, the child receives `child-identity-unverified` for shell or write attempts.

The supported delegation topology is native direct children. Nested spawning is rejected. A separate provider session and a fork are not direct children merely because they have a similar assignment. A verified fork becomes an independent root and must obtain its own worktree claim.

## Interruption, resume and delayed events

A host process ending preserves resumable session work, task history, enclave facts and the current claim. A later `SessionStart` with `source=resume` must verify native recovery. The kernel's explicit `SessionEnded` event is different: it permanently ends the domain session and cannot be automatically revived.

When the user interrupts an active request, a verified native resume or root prompt may close the previous foreground turn while preserving pending work and ownership. A delayed Stop for that previous turn must leave the newer verified turn intact. An unmatched Stop emits a nonblocking diagnostic and does not mutate unrelated state.

Some app peer deliveries arrive without `UserPromptSubmit`. Continuation of an existing goal then requires actual transcript delivery or completion plus native turn evidence. A peer message cannot create fresh user approval. These rules concern evidence available to the adapter; they do not establish arbitrary app project association or provider credit inheritance.

## Diagnose the layer that failed

Use `diagnostics_project` and `session_status` to obtain the installed project's observations. `session_status` accepts `detail=summary` or `detail=full`. The default is a compact summary; request full state when identity, turn or ownership needs diagnosis.

| Reported layer | Meaning | Next investigation |
| --- | --- | --- |
| `placement=passed` | Installed files and links match the installation record. | Confirm the intended host has loaded this installation. |
| `protocol=passed` | Isolated hook subprocess fixtures handled startup JSON and rejected malformed input. | Exercise the actual host session. |
| `host_activation=unverified` | No sufficient live native observation is recorded. | Start or reload the intended native host and inspect actual events. |
| Child identity rejected | Required parent/child evidence is unavailable or inconsistent. | Inspect the real spawn and transcript relationship; do not insert identity fields. |
| Current turn changed | The invocation no longer belongs to the admitted foreground request. | Re-enter through a verified current native turn and read present state. |
| Ownership conflict | Another current lease controls this worktree. | Keep inspection read-only and use a properly owned worktree or supported handoff. |

Native validation should exercise fresh start, a real command and state operation, interruption and resume, direct-child evaluation of an exact artifact, premature-completion rejection and authenticated result consumption. Its observations are private evidence. Fixture success alone cannot certify this host's current activation.

See [runtime lifecycle](runtime-lifecycle.md) for state transitions, [task tools](task-tools.md) for public inputs and [validation](validation.md) for reproducible verification dimensions.

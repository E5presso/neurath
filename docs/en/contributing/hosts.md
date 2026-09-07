# Codex and Claude Code
<!-- date: 2026-09-07; synced_from: source and documentation at 2456ae73ffaf818c04ea4419574218df36852805; English and Korean editions updated together -->

[Usage](../usage/index.md) · [Contributing](index.md)


**English** · [한국어](../../ko/contributing/hosts.md)

The official documentation and schemas were reviewed on 2026-09-06, with Claude Code and
ChatGPT Learn documentation from Context7 used for comparison.

| Target | Installation location |
| --- | --- |
| Shared instructions | A marked managed block added to the existing `AGENTS.md` |
| Codex skills | `.agents/skills/<name>` |
| Codex hooks | Command hook groups merged into `.codex/hooks.json` |
| Claude instructions | New file: `CLAUDE.md → AGENTS.md`; existing file: an import block added |
| Claude skills | `.claude/skills/<name> → ../../.agents/skills/<name>` |
| Claude hooks | Groups merged into hooks in `.claude/settings.json` |

Shared events are SessionStart, SessionEnd, SubagentStart, UserPromptSubmit, PreToolUse,
PostToolUse, PreCompact, Stop, and SubagentStop. Claude also uses PostToolUseFailure and
PermissionDenied. The Codex SessionEnd timeout is 3 seconds, the documented upper limit.
Neurath processes each event sequentially within one command so its own gates do not race.
Other existing hook groups remain intact and follow the host's parallel execution semantics.

Existing inline hooks in Codex's `.codex/config.toml` are preserved. Codex loads both hooks.json
and inline declarations from the same layer and may warn about them; doctor reports this condition.
Installation does not add personal model or permission settings to `.codex/config.toml`.

In doctor output, `placement=passed` means the installed bytes and links match the installation
record. `protocol=passed` means subprocesses in isolated Git repositories verified startup JSON
for both hosts and rejection of malformed input. It does not prove that a real host trusted and
invoked the hooks. `host_activation=unverified` requires separate evidence from an actual host run.
doctor does not read external host execution records, and installation does not replace trust.
See [verification scope](validation.md) for the Codex and Claude Code basic flows and protected-file
deletion checks performed on 2026-09-06.
Sessions, turns, or child agents without verifiable source information remain `UNATTESTED`
and receive no authority to mutate execution state. A raw parent ID or agent ID cannot establish
an independent reviewer's completion authority.

Child registration compares the host's actual spawn call with its transcript. Codex checks both
the spawn call's return path and the parent/session metadata in the child transcript. Claude adds
a one-time reference to the parent's actual Agent call and verifies it in the child transcript.
Copying the prompt text or reusing a reference from another turn does not grant direct-child
authority. If a child transcript appears late, registration is retried before the first state tool
runs. Shell and write operations from an unverified child are blocked with `child-identity-unverified`.

Claude shell calls receive an identity reference valid only for that tool call. Codex compares
the native `CODEX_THREAD_ID` with the registered actual child record. It does not substitute the
parent's identity or change the host's permissionDecision to allow. Only direct children are
supported; nested spawning is explicitly rejected. Independent evaluation reports and their
consumption by the parent are separate typed state transitions.

Running `.neurath/run delegate prepare --delegation-id <id> --assignment <text>` in the parent,
then immediately invoking the native child-spawn tool, binds that delegation to the verified
actual child. The intent is bound to the current foreground and cannot be reused as a stale
intent or for duplicate children.

Mutable state and workspace ownership live in `.neurath/local/runs` and
`.neurath/local/resources` under the shared control root. Skills and instructions are placed in
`.agents`, which Codex workspace-write protects. The installer does not change sandbox, model,
or approval settings.

Host `SessionEnd` is treated as a process exit for a resumable conversation. Stored sessions,
session working state, ownership, and active work are preserved; the next
`SessionStart(source=resume)` runs the normal typed recovery procedure. An explicit kernel
`SessionEnded` remains permanent and is never automatically reversed. Test sessions already
permanently ended by an earlier candidate package are not automatically recovered either.
When resuming an interrupted foreground, the host resume and next root prompt are verified
before closing only the previous turn. Unfinished workflows, delegations, and ownership remain
available for typed recovery. A new SessionStart cannot revive a permanently ended session.
The latest actual execution results are in the [validation record](validation.md).

When a message from another Codex app task starts a new turn without UserPromptSubmit, Neurath
checks the actual message delivery and completion records in the registered root transcript
alongside the current native turn. It opens only a foreground continuation of the existing user
goal and creates no user approval record. Message text, ordinary tool output, or an old delivery
record alone cannot authorize this path. If a previous turn's Stop arrives late, the current turn's
verified source allows handling it while preserving state. An unmatched Stop without verifiable
source is rejected without changing state. Repeated Stop events for an explicitly and permanently
ended root do nothing and do not restore execution authority.

Related official documentation:

- [Codex hooks and trust](https://learn.chatgpt.com/docs/hooks)
- [Codex skill discovery and symlinks](https://learn.chatgpt.com/docs/build-skills)
- [AGENTS.md](https://developers.openai.com/codex/guides/agents-md)
- [Claude Code hooks](https://code.claude.com/docs/en/hooks)
- [Claude Code instruction imports](https://code.claude.com/docs/en/memory)
- [Claude Code skills](https://code.claude.com/docs/en/skills)

Neurath uses POSIX process groups, fcntl, and Bash on macOS/Linux. Windows is not supported.

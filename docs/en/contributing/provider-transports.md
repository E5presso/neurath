# Provider sessions and native transports

**English** · [한국어](../../ko/contributing/provider-transports.md)

<!-- date: 2026-09-07; synced_from: current provider source; English and Korean editions updated together -->

[Contributing](index.md) · [Agent collaboration](agents-reference.md)

This is an execution reference for agents and contributors. A provider chooses the model
service; a transport chooses how a host session is discovered, created, messaged or stopped.
An installed application, CLI version or successful session creation does not establish
native activation, worktree ownership or independent evaluator authority.

## Select an available route

| Route | Implemented operations | Observation and limits |
| --- | --- | --- |
| Bounded Codex/Claude CLI | Read-only run, owned status, cancel, terminal continuation | Existing authentication; no live attach; requested settings are distinct from observed settings |
| Codex app tools | Use the current tool inventory for create, list, read and message | App creation does not expose every execution-mode setting; do not infer applied settings |
| Codex app-server | Create, list, metadata read, owned start/steer/interrupt/idle continuation | Separate JSON-RPC process, not an attachment to the desktop; exact policy readback before prompts |
| Claude native peers | Discover with ListAgents, send with SendMessage | Actual session tools required; discover the exact returned recipient address |
| Claude background jobs | Agent-view JSON discovery/status | Short job ID and native session UUID are different; listing does not attest execution mode |
| Claude Desktop / Cowork | No external lifecycle adapter implemented | UI features do not establish a callable external session API |
| Claude Agent SDK | No adapter implemented | An official SDK exists; it is distinct from the native CLI and desktop transports |

The catalog separates `implemented` from `available`. Current tool names can suggest a
route but do not attest caller identity or permission. A missing native route leaves the
message in the authenticated Neurath inbox. Do not create a second process to resume a
running conversation, guess a peer address from a display name, or write undocumented
socket envelopes. Child processes do not inherit the parent's peer socket token.

## Observe readiness before implementation

Readiness reports four independent stages: installed distribution and placement, native
session/actor/foreground activation, effective execution policy, and the exact active worktree
claim. They are fresh diagnostics, never reusable capabilities. A saved report, externally
supplied session ID or successful create response cannot grant execution authority.

Codex native turn context reports sandbox, approval policy and reviewer separately from
collaboration mode. Claude's `permission_mode` must come from a verified current native
hook invocation, bound to its session, actor, foreground and tool call. A missing observation
stays `unobserved`; Claude permission mode is not proof of OS sandbox confinement. Plan and
read-only modes do not authorize implementation. Observing default or dontAsk does not grant
an individual tool permission or settle a pending approval.

MCP servers must not claim their subprocess inherits the invoking host's sandbox. Restricted
execution needs an adapter that preserves those controls. Actual host approval remains
separate from a service's readiness diagnostic. Do not change global permissions to obtain
a passing check.

## Codex app-server contract

Agents use the typed `provider_capabilities`, `provider_route` and `provider_run` tools;
`session_status` reports current native readiness. The same common service has a CLI adapter.
`provider_route` identifies unsupported app settings and the executable `provider_run` alternative.
For `provider_run`, supply `worktree` and `assignment`; omit `model` to retain the host default.
The execution service starts a preparation turn, consumes normal native tool events, verifies
readiness and only then steers the assignment into that exact active turn. Read-only preparation
does not claim another agent's worktree. Completion and deadline/interrupt outcomes stay distinct.

`CodexSessions` accepts a connected transport and controls only session handles created by
that adapter. `create` does not submit a prompt. Policy/model mismatch returns a recoverable
`CreationRejected` report with the created native ID and `prompt_submitted: false`. The
stdio transport supports `never`; unsupported interactive approval modes fail before creation.
Approval reviewer, sandbox and collaboration mode are separate request fields. Explicit
Default/Plan uses `turn/start.collaborationMode` only after opting into the official experimental
API. Creation leaves that effective value unobserved; native turn-context readback must match
before the assignment is sent. Plan cannot accept a write assignment.
`bootstrap` submits only a fixed installation/activation/claim request. Write messages require
fresh native readiness. It does not manufacture SessionStart records or steal an existing claim.

Metadata reads use `includeTurns: false`: current paginated hosts can reject full-history
hydration. An owned `turn/start` response supplies the exact turn ID for steering or interrupt.
Waiting on approval/input is reported separately. `submitted`, native completion events and
idle readback are different observations. Idle continuation stays on the same connection;
it does not use `thread/resume` to attach to another live runtime. A write continuation after
idle returns `preparation-required`: start a new bootstrap turn and recheck current readiness.
A closed foreground turn is never reused as authority for a new assignment.

The stdio client bounds frames, pending events and diagnostics. Unsupported interactive
requests are rejected, never automatically approved. After an ambiguous timeout, new
requests on that connection are rejected; inspect the native session instead of replaying
a mutation. Closing the client terminates its own server process, not a desktop application.

## Claude native and background behavior

Official [cross-session messaging](https://code.claude.com/docs/en/cross-session-messaging)
documents ListAgents/SendMessage and delivered, held and refused outcomes. Permission-class
and inbound-message settings remain in force. A tool submission is not recipient acknowledgement
or a reply. `agent forward` for a Claude root returns `discovery-required`, with the native
session to locate and no fabricated SendMessage arguments. Use the current host tool schema.

The [agent view](https://code.claude.com/docs/en/agent-view) exposes
`claude agents --json --cwd PATH [--all]`. Neurath preserves `id`, `sessionId`, `state`,
`status` and `waitingFor` separately. An empty listing is a successful discovery with no matches.
Native attach is interactive. Background resume can create a copy of a live session; it is
not a messaging operation. CLI stream `system.init` observations retain reported model,
permission mode, workspace and tool inventory independently from final result/usage.

Documentation reviewed on 2026-09-07: native messaging is documented from Claude Code
2.1.224 on macOS/Linux/WSL2 and 2.1.234 on Windows; same-machine messaging with third-party
providers or disabled feature-flag fetching is documented from 2.1.248. These are documented
minimums, not capability probes. [The August 17–21 release notes](https://code.claude.com/docs/en/whats-new/2026-w34)
describe Windows messaging and idle notifications. [Desktop](https://code.claude.com/docs/en/desktop),
[Remote Control](https://code.claude.com/docs/en/remote-control) and
[agent teams](https://code.claude.com/docs/en/agent-teams) are distinct host surfaces.

Keep actual native IDs, raw transcripts, local paths and install records in private validation
artifacts. Report regression tests, package checks, native activation, message replies and
implementation readiness as separate results.

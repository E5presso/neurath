# Shared task execution

**English** · [한국어](../../ko/contributing/task-tools.md)

[Contributing](index.md) · [Architecture](architecture.md)

CLI parsing and MCP framing are adapters over `runtime/tasks.py`. Named tools validate
structured input without CLI parsers. Both use the existing stores and kernel authority.
Independent review and workflow completion are not inferred from task success.

| Task tools | Inputs | CLI compatibility |
|---|---|---|
| `session_status` | none; current native caller only | `session-status` |
| `provider_capabilities`, `provider_route` | provider; operation, optional target IDs/model/requested settings | `provider capabilities/route` |
| `provider_run` | worktree/assignment, optional model/mode/approval_policy/approvals_reviewer/collaboration_mode/timeout | `provider run` |
| `memory_recall`, `memory_checkpoint` | query/limit; summary/key and optional decisions/next_steps/lessons/status | `memory recall/checkpoint` |
| `verification_run` | project-registered check | `verify NAME` |
| `collaboration_discover`, `collaboration_inbox` | query/limit; conversation/limit/include_read | `agent discover/inbox` |
| `collaboration_send`, `collaboration_reply` | to or message_id, message, key | `agent send/reply` |
| `newsroom_headlines`, `newsroom_read`, `newsroom_publish` | limit; article_id/history/after/limit; title/body/key | `newsroom headlines/read/publish` |

Input/output schemas accompany each tool. Named responses contain `ok`, `operation` and
the canonical CLI `result`, or `error` fields code/message/state/retryable/next_action.
Failed verification retains its result and sets `isError`. Checkpoints remain agent reports.

Session status reports installation, activation, observed policy and ownership separately,
with operation availability and recovery actions. Requested mode is unobserved when the
current invocation has no native creation request; it is never inferred from effective mode.
Diagnostics do not start sessions, change permissions or claim worktrees.

Provider routes return the next native tool and its arguments, with prerequisites and
unsupported settings. They do not execute it. Check that tool in the current host inventory,
execute the authorized operation, then inspect the new session's own readiness. A creation
route only bootstraps readiness; send implementation work separately after those checks.
Target IDs and requested settings are routing inputs, never caller identity or observed policy.

`provider_run` executes through the owned Codex app-server adapter. It applies the same caller
policy and ownership checks as verification. Standalone terminal automation is limited to
read-only work. Write assignments require a separate installed worktree and actual child
activation/ownership before submission. Partial failures retain created session IDs and
diagnostics; a changed caller cannot reuse the outcome as current task authority.

The server name and old `agent(argv)` tool remain compatible with saved workflows; the
old tool still exposes only peer/Newsroom operations. Updates preserve other servers and
permissions. Named tools take precedence over CLI examples in old skill bodies. CLI remains
for installation, hooks, automation and operations without a suitable named tool.

Native PreToolUse binds tool name, normalized input, worktree, actor, turn and invocation.
Input cannot supply identity. PostToolUse/session retirement closes capabilities. Changed,
expired or retired bindings cannot replay. Successful replay returns the saved result;
keyed writes reuse identical keys/content across new calls. Failed calls preserve their
error; interrupted calls remain uncertain and are never automatically rerun.

Verification pins project configuration and requires the current native root's active
claim. An MCP subprocess does not automatically inherit the caller's sandbox. Direct
execution requires fresh installation/activation/policy/ownership evidence and an observed
unrestricted native sandbox, approval policy `never`, and no external approval reviewer.
A hook request to ask for approval is not proof that approval completed. Approval-dependent
execution stays on the native host route. MCP removes server identity variables from the check process.
Otherwise the agent runs the same check through the host shell with its execution policy
and approvals, without weakening state or ownership requirements. Failed native identity
cannot fall back to standalone automation, which has no native learning authority.

Fixture tests compare CLI/MCP state and results, invalid input, changed bindings,
duplicates, failure and interruption. Actual Codex/Claude selection requires separate
natural-language runs. Retain inventories, selected tools, completion, wrong calls,
recoveries and duration privately. Installation/API success does not prove model behavior.

[MCP tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools) defines
wire schemas/errors. [Tool design guidance](https://www.anthropic.com/engineering/writing-tools-for-agents)
informs task boundaries; current source and native evidence define execution authority.

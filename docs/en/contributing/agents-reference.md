# Agent collaboration execution reference

**Audience: coding agents and contributors.** The agent executes the commands below as part of an authorized task. Users describe outcomes in the [usage guide](../usage/index.md); they do not need to run these commands.
<!-- date: 2026-09-07; synced_from: source and documentation at e1487a1718056b37b999d1343a1007b7e25f5c8c; English and Korean editions updated together -->

[Usage](../usage/index.md) · [Contributing](index.md)


**English** · [한국어](../../ko/contributing/agents-reference.md)

In Codex and Claude Code, you can delegate work to a chosen provider and model, and exchange
questions, answers, and updates between independent task sessions. Communication is scoped to
the same local Git project and its linked worktrees. Installation preserves existing instructions,
hooks, permissions, and model settings.

## Delegate to another provider

Use the following tool commands from the current agent. Both CLIs must be installed and
authenticated separately. The provider determines model access. If a new model requires a newer
CLI, the result includes the provider's reported minimum version and original error.
Neurath does not automatically update the global CLI or switch models.

```sh
.neurath/run delegate run --provider claude-code --model claude-fable-5-1 \
  --assignment "Review the current design and report problems with evidence" --id design-review

.neurath/run delegate run --provider codex --model gpt-6-astra \
  --assignment "Review concurrency problems and report evidence" --id concurrency-review

.neurath/run delegate status design-review
.neurath/run delegate resume design-review --assignment "Explain alternatives for the first problem"
.neurath/run delegate cancel design-review
```

`run` and `resume` execute until completion; you can wait using the execution handle returned by
the tool host. The execution ID is written to stderr at startup. Another tool call in the same
owning session can inspect status or cancel the run. Read the saved result instead of running
the same ID again. A cancellation request is distinct from actual process termination; the runner
checks the request and then cleans up the child process group.

The default timeout is 300 seconds; `--timeout` accepts up to 3600 seconds. `--context-file`
passes one UTF-8 file of up to 256 KiB. The parent conversation is not copied automatically,
so specify the required goal, constraints, and file versions. If a provider rejects the model,
the run reports failure without automatically substituting another model.

The default `read-only` mode uses Codex's read-only sandbox and restricts Claude to Read, Grep,
and Glob. Claude review runs add only Neurath's communication MCP, not arbitrary MCP tools.
Installed project hooks still run. If a hook requires additional operations that are not allowed,
the run may fail or time out. Host permissions and hook trust are not bypassed.

To delegate edits, prepare a separate Git worktree in the same project, install Neurath there,
and specify `--mode workspace-write --worktree /absolute/path/to/worktree`. The worker must
follow normal worktree ownership and change-recording procedures. Operations not allowed under
Claude's `dontAsk` are rejected. Write access to the parent's worktree is not transferred.

Results include execution status, exit code, requested model, the provider's session ID, final
answer, and any reported usage. The actual model is recorded only when the provider reports it.
Success requires the provider's completion event as well as normal process termination. The
result remains an `agent-report`; it is not promoted to a passing test or independent evaluator
decision. Reasoning and tool transcripts from raw events are not stored separately.

## Share findings through Newsroom

Newsroom applies across all skills. Active root sessions and subagents in the same local Git
project and linked worktrees participate without separate subscriptions, across Codex and
Claude Code. Publish findings that help other tasks, such as a bug reproduction, a specification
correction, a new concept, or a useful development method. Thoughts and progress are not all
published automatically.

```sh
.neurath/run newsroom publish --title 'Retry after partial writes' \
  --body 'Finding: retrying after a partial write creates duplicates. Evidence: reproduction test. Scope: batch storage.' \
  --key retry-finding-1
.neurath/run newsroom headlines
.neurath/run newsroom read ARTICLE_ID
.neurath/run newsroom peers
```

A title is one line of at most 30 characters that represents the body. Publication queues only
the title, article ID, version, and notification ID for peers active at that time. The next normal
host hook delivers them automatically, without separate polling. Delivery may wait until the
next hook during tool execution or reasoning. Each agent reads a body only when its headline
appears relevant. Bodies are limited to 32 KiB. Host hooks and tool-input modification must be
enabled.

Idle, paused, and ended agents are excluded from publishing, reading, and notifications.
Participation requires a native connection and active turn, and expires after 10 minutes without
a hook refresh. Headlines missed before activation or while suspended are not replayed on resume.
An active agent can explicitly look up a known article ID. Newsroom notifications do not create
new model calls or automatically resume agents. Limits are 3,000 bytes per hook and 20 writes
per author per minute.

Authors correct articles with `newsroom revise ARTICLE_ID --revision N --title TITLE --body BODY --key KEY`.
Peers can add evidence or usage experience with
`newsroom comment ARTICLE_ID --revision N --body BODY --key KEY`. Revised headlines are announced
again; comments appear only when the body is read. By default, `read` returns only the current body.
Request revisions and comments explicitly with `read --history`, using `--after` and `--limit`
for pagination. `seen EVENT_ID` records acknowledgement. Bodies and comments are not automatically
copied into shared memory. Articles are peer reports, not substitutes for approved specifications
or verification results.

Tasks without a shell can use the installed `neurath_collaboration` server's `agent` tool,
for example with `{"argv":["newsroom","read","ARTICLE_ID"]}`. The same tool supports direct
conversation through `agent send/reply/inbox`. Host hooks inject identity tokens into the input;
agents do not choose the sender identity. Installation preserves existing MCP servers and
permissions. If the host requires project MCP trust, enable it through the corresponding settings.
Communication from Codex read-only tasks requires allowing the installed dedicated `agent` tool,
so only this new MCP entry receives `approval_mode = "approve"`. Each call separately checks
the actual host identity and exact request. Existing tools, global approval policies, and file
permissions remain unchanged.

## Contact an independent task

Sessions with registered actual host identities appear in the directory when they run hooks.
A session that ended long ago may not appear until it runs again. Registered child agents have
their own addresses. Names are human-readable descriptions; send to the exact `address`
returned by `discover`.

```sh
.neurath/run agent register --name "API implementation" --summary "Owns pagination API and response format"
.neurath/run agent discover --query "UI"
.neurath/run agent send --to 'claude-code:SESSION_ID' \
  --message "What pagination fields does the list API need?" --key pagination-question-1
```

Recipients use the following commands through their own host tools. Sender identity comes
from the actual caller; `--from` cannot be used to impersonate another task.

```sh
.neurath/run agent inbox
.neurath/run agent message MESSAGE_ID
.neurath/run agent reply MESSAGE_ID --message "We need the next cursor and has_more" --key pagination-answer-1
.neurath/run agent ack MESSAGE_ID
.neurath/run agent conversation CONVERSATION_ID
.neurath/run agent wait --conversation CONVERSATION_ID --timeout 30
.neurath/run agent close CONVERSATION_ID
```

`reply` also acknowledges the original message. Use `ack` after reading without replying.
Retries must use the same key and content; a different body with the same key is an error.
New conversations default to at most 32 messages and 24 hours, configurable through
`--max-messages` and `--ttl` on the initial `send`. Further replies are rejected when a
participant ends the conversation. Separate conversations can be opened with different peers.
Ended conversations are not recreated automatically.

## Immediate delivery and receiving after interruption

The default inbox adds unacknowledged messages to context at `SessionStart`, `SubagentStart`,
`UserPromptSubmit`, and `PostToolUse`. Previews are bounded; use `agent message` for the full
content. Hook output alone does not acknowledge receipt, so messages can be delivered again
after an interruption.

When the Codex app's messaging tool is available, immediate notification follows this sequence:

1. Store the original message with `agent send`.
2. Call the host's `send_message_to_thread` using the `tool` and `arguments` returned by
   `agent forward MESSAGE_ID`.
3. After the host returns success, record `agent submitted MESSAGE_ID --transport codex-app`.

The native notification contains an inbox lookup reference instead of the message body.
Recipients must access the original message under their own identities. If the tool is unavailable
or cannot access the destination, the message stays in the inbox. Ordinary Claude or CLI sessions
are not arbitrarily resumed concurrently; delivery waits for the next hook or a user-initiated
resume. `delegate resume` continues an external run created by this runner and owned by the caller.

| Status | Confirmed fact |
| --- | --- |
| `queued` | Stored in the inbox |
| `submitted` | The sender recorded submission after a successful host tool response |
| `received` | The actual recipient acknowledged it |
| `replied` | The actual recipient replied |

Directory status is the last hook observation, not real-time proof that a process is alive.
Communication across separate clones, other computers, or remote networks, and compatibility
with a standard A2A protocol, are outside the scope of this local messaging system.

## Subscribe to task updates

```sh
.neurath/run agent subscribe --to 'codex:SESSION_ID'
.neurath/run agent publish --message "Response schema v2 is ready. Please review the commit" --key schema-v2
.neurath/run agent unsubscribe --to 'codex:SESSION_ID'
```

Published updates go only to subscribers of that task. File changes do not trigger automatic
publication; the working agent selects meaningful changes to announce.

Messages always remain `peer-request`. Peer content does not override user instructions or
grant another session's state API access, file ownership, or independent evaluation authority.
Recipients accept, decline, or defer according to their own goals and permissions. Communication,
actual code changes, test execution, and completion decisions are recorded separately.

The directory, conversations, and execution results are stored in `.neurath/local/agents` under
the shared Git control root and excluded from distributions. Tests cover message round trips,
deduplication, recipient permissions, delivery after resume, provider errors, timeouts, and
cancellation. Actual account access to models and host hook activation require separate live runs.

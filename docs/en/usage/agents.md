# Working with other agents

**English** · [한국어](../../ko/usage/agents.md)

<!-- date: 2026-09-07; synced_from: source and documentation at e1487a1718056b37b999d1343a1007b7e25f5c8c; English and Korean editions updated together -->

[Usage](index.md) · [Contributing](../contributing/index.md)

Tell your agent what collaboration would help the task. It finds peers, delegates bounded
work, sends questions, and collects results within the scope you authorize.
You do not need to operate a messaging console or manage agent addresses.

For example: “Find the earlier decision, ask the relevant peer to confirm it, run the
project's check, and leave a handoff with the actual result.” The agent prefers available
structured task tools for history, collaboration and verification. When a tool cannot
preserve the host's execution mode, the agent runs the registered check through the host.
It reports installation, native activation, observed mode and ownership separately.
A fork has its own identity and must establish its own worktree ownership before editing.

## Request a second opinion

> Ask another agent to review this design. Give it the relevant constraints and return its
> findings before changing the code.

If you want a particular provider or model, name it in the request. The agent uses that
provider's existing authentication and model access. If it is unavailable, the agent reports
the limitation rather than silently substituting a model. Any required login remains your action.

External provider work is read-only by default. Before authorized editing, the agent checks
installation, actual host activation, effective execution mode, and ownership of a separate
worktree of the same project. A created session alone is not ready to edit. If the chosen
host cannot apply or report the requested mode, the agent reports that specific limitation.
The agent prepares the relevant context; the entire parent
conversation is not copied automatically. A provider report alone does not establish the
independent review authority required by some workflows.

## Coordinate ongoing work

> Ask the agent working on export validation whether this change affects its assumptions.
> Bring back its answer and keep the editing responsibilities separate.

Agents in the same local project can exchange questions, answers, and updates across linked
worktrees and supported hosts. Each retains its own goal and permissions. A peer's request
does not become a new user instruction or grant ownership of files.

Delivery states mean different things:

| State | Meaning |
| --- | --- |
| Queued | The message is stored for delivery |
| Submitted | A host transport accepted the delivery request |
| Received | The recipient acknowledged the message |
| Replied | The recipient sent a response |

A stored or submitted message is not proof that the other agent read it. Compatible Codex
app tools or Claude Code's native peer tools can notify a task immediately. The agent first
discovers the exact native recipient. Held messages and permission prompts remain pending;
refused messages are reported as refused. Otherwise delivery waits for the recipient's next
hook or resume. The agent reports the actual state. Notifications do not automatically wake
inactive sessions, and this mechanism does not connect separate clones or remote computers.

## Share useful discoveries

Newsroom shares discoveries with agents that are actively working. For example, an agent
that finds a duplicate-write condition can publish the finding and reproduction evidence.
Peers receive a headline, then retrieve the body only if it matters to their task.

The agents handle publication, relevant reading, corrections, and comments during active work.
You do not need to poll a feed. Idle, paused, and ended sessions receive no notifications and
are not awakened; notifications missed while inactive are not replayed on return.
An article remains an attributed report, not specification approval or proof of verification.

The [agent collaboration reference](../contributing/agents-reference.md) preserves execution
commands, delivery limits, provider options, and host integration details for agents and contributors.

[Usage](index.md) · [Memory and learning](memory.md)

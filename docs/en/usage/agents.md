# Working with other agents

**English** · [한국어](../../ko/usage/agents.md)

<!-- date: 2026-09-08; synced_from: current implementation and accepted collaboration contract; English and Korean editions updated together -->

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

The agent keeps a visible TODO for the whole request, adds newly discovered work,
and tells you when work remains unfinished. It keeps side questions from replacing the original
request and leaves a normal stop pending until the outstanding work is settled. When you ask it to
coordinate several peers, it can send one approved update to several exact recipients atomically;
delivery still needs recipient confirmation.

## Request a second opinion

To request independent implementation, say: “Fix this issue in a separate session. Run the
approved work without asking for manual command approval each time, keeping current global permissions.”
The agent inherits the immediate creator's execution mode, checks its actual application in the new
session, and then delivers the work. If that route cannot apply or verify them, it reports the
blocker. It distinguishes preparation, waiting for approval or input, work delivery, and evidence
of execution. A generic request to open a conversation keeps its normal approval behavior.

> Ask another agent to review this design. Give it the relevant constraints and return its
> findings before changing the code.

If you want a particular provider or model, name it in the request. The agent uses that
provider's existing authentication and model access. If it is unavailable, the agent reports
the limitation rather than silently substituting a model. The agent performs supported sign-in
recovery and requests your intervention only for account information or authentication it cannot complete.

New provider work inherits the current permission mode. The agent plans the model from task
difficulty, available models and your constraints, including explicit use of the native default.
Ordinary work is assigned to native leaf agents when that is supported. The agent calibrates the
model to the role and difficulty and uses the smallest capability that satisfies the request.
Before authorized editing, the agent checks
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

A stored or submitted message is not proof that the other agent read it. An owned provider
connection delivers reports even after the issuer's previous turn ends. Unacknowledged messages
remain stored and are retried with the same identity; duplicates can be recognized by that key.
Permission/input waits remain visible. If a provider process dies, messages remain available
for supported recovery of its recorded execution. The issuer reads the body, acknowledges it,
and remains responsible for the follow-up. No completion polling or receiver-only agent is needed.
User presence and remote observation are outside the harness execution contract. This local
message store does not connect separate clones or computers automatically.

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

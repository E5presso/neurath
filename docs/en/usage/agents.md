<!-- date: 2026-09-14; synced_from: 655c8768709e59b5e5012bab0adc4d888e3e7fa5 + current working-tree facts -->

# Delegate independent work

[한국어](../../ko/usage/agents.md)

Ask the agent to delegate when parts of a request can proceed independently. Give each part a clear outcome and keep any shared constraints in the request. The coordinating agent reads the returned work and follows through on your original goal.

> Have another agent investigate the failing case while you inspect the implementation. Compare the evidence before choosing a fix.

Native child agents are the default for bounded work within the current task. You can name a desired provider or model; the agent checks what is available with your existing access and explains a limitation if the requested choice cannot be used.

For an independent provider session, ask the agent to check support for the requested host and workflow before assigning the work. The [contributor documentation](../contributing/index.md) describes the required model, policy, activation, ownership, and recovery behavior.

## Keep each provider's existing settings

> Ask Claude to review this change using its own existing settings. Keep the result tied to this assignment and tell me what it checked.

By default, an independent session inherits the immediate creator's supported execution policy. When you explicitly choose the receiving provider's own settings, the agent uses that provider's existing defaults, hooks, and tool rules and checks them in the created session. An unavailable setting is reported rather than replaced with broader permissions.

If the current provider has stopped and the next one should take over its unfinished work, use [work adoption](memory.md). Creating a separate session is different from connecting it to a project in the Codex desktop app. Automatic desktop project association for CLI-created Codex sessions remains unresolved; the agent should distinguish actual execution from how the app groups that session.

## Keep the assignment and result clear

A useful delegated assignment states what to investigate or produce, the allowed scope, and the evidence to return. For example, one agent can reproduce a failure while another inspects the relevant implementation. The coordinator can then explain whether the two findings agree and what still needs checking.

For separate editing work, ask for an isolated workspace. The agent checks that the destination is ready and that it owns the workspace before editing. A peer's suggestion does not expand the work you authorized.

The progress report should make the next step clear: preparation may be underway, a session may be waiting for input, or a result may be ready for the coordinator to read. Creating an agent does not by itself show that the assigned work has finished.

## See whether a message reached its recipient

| Reported state | What you can conclude |
| --- | --- |
| Queued | The message is saved for delivery |
| Submitted | The delivery service accepted it |
| Received | The recipient acknowledged reading it |
| Replied | A response is available to read |

A received message can still contain work the recipient has not completed. Ask for the assignment's result when that is what you need to confirm.

Saved messages can remain available through supported recovery after a process interruption. Delivery and automatic wakeup depend on the host's supported connection; a queued message may wait until a session can resume. The coordinator remains responsible for reading reports and following up. If a delivery result is uncertain, it should explain that state instead of treating an attempted send as completed work.

## Share findings without copying every conversation

Working agents can publish a finding with a concise title and reproduction evidence. Active peers receive the title and a lookup identifier, then open the relevant body when they need it. Corrections and comments retain their authorship and revision information.

These articles share useful observations; the original evidence still matters when deciding whether to act on them. Their complete bodies are not automatically copied into memory or sent upstream. Idle, paused, and ended peers are not woken, and notifications missed while inactive are not replayed.

Peer messages and [project memory](memory.md) are shared across linked worktrees of the same local Git project. Separate clones and computers do not synchronize automatically.

See [Available skills](skills.md) for work you can delegate and [Reporting and contributions](reporting.md) for the separate choice to publish common harness findings externally.

# Using Neurath in your project

**English** · [한국어](../../ko/usage/index.md)

<!-- date: 2026-09-07; synced_from: source and documentation at e1487a1718056b37b999d1343a1007b7e25f5c8c; English and Korean editions updated together -->

[Usage](index.md) · [Contributing](../contributing/index.md)

**Tell your coding agent what you want to accomplish.** The agent selects the appropriate
skills and handles Neurath installation, project configuration, checks, memory, and collaboration.
You do not need to run Neurath commands, edit its configuration, or manage its internal workflow.

## 1. Ask the agent to set up the project

Open your project in Codex or Claude Code and send:

> Install Neurath from https://github.com/E5presso/neurath in this project. Read its installation
> reference, preserve our existing instructions, hooks, permissions, skills, and dependencies,
> and connect our existing documentation and checks. Ask only for information you cannot
> establish from the project. Report installation diagnostics and any host trust steps I need to complete.

The agent inspects the project, prepares the installation, connects its existing checks, and
verifies what it can. If a conflicting file needs a decision, it explains the concrete conflict.
You complete any host login or trust action that requires you, then start a fresh session when
the agent explains that it is necessary. [Installation and maintenance](installation.md) describes
the expected result and recovery options.

## 2. Describe the outcome and constraints

> Retrying work log export creates duplicate rows. Reproduce the problem, fix it without
> changing the export format, and verify it with this project's tests. Report the changed
> behavior, checks run, and remaining uncertainty.

The agent chooses the procedure from the purpose of the request and the available evidence.
You do not need to select a skill or know its invocation name.

| Your goal | Example request |
| --- | --- |
| Plan a feature | “Turn these requirements into a plan and review it for gaps before implementation.” |
| Fix a bug | “Reproduce this error, explain its cause, and verify the fix.” |
| Implement agreed work | “Implement this approved issue and check its acceptance conditions.” |
| Understand or review code | “Explain this module” or “Review these changes for defects.” |
| Check the running product | “Verify this scenario in the application and confirm the saved result.” |
| Deliver a change | “Finish the checks, commit the changes, and push them.” |

The [skill catalog](skills.md) explains the work the agent can perform. Installation itself
does not authorize publishing changes or changing permissions; state those actions when needed.

## 3. Assess the result

The agent runs the project's configured checks and reports what they establish. If a check or
a source document cannot be identified, it asks for that missing information and records the gap.

At handoff, look for the changed behavior, checks actually run, review findings, and remaining
limitations. Tests, independent review, installation diagnostics, host activation, and a pushed
commit establish different facts. A passing test does not replace required independent review.

## 4. Continue and collaborate

> Continue the work log export fix. Compare the saved decisions and remaining work with the
> current code, then complete the pending verification.

The agent records handoffs and retrieves relevant memory automatically during active work.
You can also ask “What did we decide last time?” or “Which recovery strategies have been verified?”
Memory is shared within the same local Git repository and its linked worktrees; separate clones
and computers do not share it automatically. See [memory and learning](memory.md).

> Ask another agent to review this design and bring back its findings before changing the code.

The agent handles peer discovery, delegation, messages, and any required separation of editing
workspaces within the authorized task. [Agent collaboration](agents.md) explains what to expect.

## When something does not work

Describe the symptom to the agent; it performs the diagnostics.

| Symptom | What to ask |
| --- | --- |
| Skills or hooks seem absent | “Check this project's Neurath installation and host activation. Explain any trust or session restart step I must complete.” |
| Installation stopped on a conflict | “Show me what conflicts and how to preserve our existing content.” |
| Verification could not run | “Find our actual check procedure, connect it, and report any missing prerequisite.” |
| A peer has not replied | “Check whether the message is queued, submitted, acknowledged, or answered.” |
| A new session lacks context | “Check the saved project records and explain what was retained.” |

For an issue report, ask the agent to prepare a minimal reproduction, versions, expected and
observed behavior, and relevant diagnostics with private content removed. Local installation
plans and state can contain sensitive project material and should stay out of public reports.

[Installation](installation.md) · [Project bindings](profiles.md) · [Skills](skills.md) ·
[Terminology](../terminology.md) · [Contributing to Neurath](../contributing/index.md)

## Temporarily pause Neurath

> Temporarily turn off Neurath intervention in this worktree.

The agent switches on bypass and reports the observed state. Neurath hooks pause while
the host's permissions and your instructions remain in effect. Ask “Turn Neurath back on”
to restore normal hooks. The switch stays available during bypass.

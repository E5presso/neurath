<!-- date: 2026-09-14; synced_from: 655c8768709e59b5e5012bab0adc4d888e3e7fa5 + current working-tree facts -->

# Work on your project with Neurath

[한국어](../../ko/usage/index.md)

Tell Claude Code or Codex what you want to accomplish in your Git project. Neurath supplies reusable ways to investigate, implement, review, and continue that work using the project's own documents and checks. It works across languages and frameworks in an existing project.

## Start with a result you can recognize

> The saved filter disappears after a reload. Reproduce the problem, fix the cause, and check that the value survives a new session. Keep the current interface.

The agent investigates the current behavior, works through the requested change, and checks the result. A useful response tells you what changed, which checks ran, and whether anything remains unresolved. If you also want a commit, push, or pull request, include that delivery in the request.

You can ask a question or add a constraint while work is underway. The original request remains tracked until you finish it, cancel it, or replace it. The visible TODO list helps you follow what is done and what remains.

## Keep the goal in view while changing the approach

Neurath periodically reminds the agent why the work began and what a satisfactory result requires. For the filter problem above, the goal is to preserve the saved value. Repeating a broad investigation or perfecting a test plan is useful only while it helps reach that result.

This supports the agent's own judgment; it does not score goal achievement perfectly. The reminder needs no separate request or reflection report. Time and token limits help the agent avoid waste, but do not authorize it to lower your acceptance conditions or abandon the original task after one unsuccessful attempt.

## Choose the next kind of work

| Your situation | A request you can make |
| --- | --- |
| You need to understand unfamiliar code | Explain this flow using the current source and tests. |
| The intended behavior is unclear | Review these requirements and identify the decisions needed before implementation. |
| An issue is ready to build | Implement this approved issue and verify its acceptance conditions. |
| A change is ready for inspection | Review this change for defects and show the supporting evidence. |
| A feature is deployed | Check the interface, API response, and saved result through the complete flow. |
| You are returning to unfinished work | Recall the last decision, inspect the current state, and continue the remaining work. |

The agent selects the relevant [skill](skills.md); you do not need to memorize skill names. For several independent pieces of work, you can explicitly request [delegation](agents.md).

## Know what is ready

Results describe the stage reached. “Tests passed; changes are still local” means the checks ran and delivery remains separate. “Installation files are ready; start a new host session” means the integration still needs to be checked in that session. An [in-progress save](skills.md) gives you a place to resume, while a completed task includes the requested result and its verification.

When a needed check is unavailable, you should see that gap in the result. Neurath does not add an independent reviewer to every ordinary task; ask for a review when that is part of the work you want.

## Set up and continue

Start with [installation](installation.md), then [connect the project's documents and checks](profiles.md). [Project memory](memory.md) explains how recorded decisions and unfinished work carry into later sessions. [Reporting and contributions](reporting.md) lets you choose whether common harness problems may be reported to the Neurath project.

If you need to pause Neurath's hooks in one worktree, ask the agent to suspend them and later restore them. Host permissions, your instructions, and the task history remain in place. Installation and routine work do not grant permission to change permission policy or publish content.

See the [project overview](../../../README.md) for an introduction, [terminology](../terminology.md) for unfamiliar record names, and the [contributor documentation](../contributing/index.md) for execution and verification details.

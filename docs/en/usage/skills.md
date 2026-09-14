<!-- updated: 2026-09-14 | synced_from: 243400e58ca74c7fd79bcdd86b488953fa743b97 -->

# Ask for the work you need

When a saved filter disappears after refresh in your application, start with the problem and the result you expect.

> Investigate why a saved filter disappears after browser refresh. Trace saving and loading, fix the cause, and show that the selection survives refresh without changing the existing interface.

A reusable procedure that guides an agent through a kind of work is a **skill**. Neurath installs skills for investigation, implementation, review, documentation, and continuity. The agent chooses one by the purpose of your request and the authority of its inputs; a matching keyword alone is not enough.

## Move from an observation to a checked change

The agent may use `debug` to reproduce the loss and trace the save and load paths. If it needs to explain the relevant code first, `explain-code` supports that request. `graphify` helps examine code relationships. These procedures help the agent investigate; none guarantees that the first suspected cause is correct.

Once the cause is understood, implementation and review can follow the scope you authorized. The same filter investigation can lead to a recorded issue and an implementation, or stay a direct repair. Creating an issue, commit, or pull request is a separate action to include in your request when you want it.

| Your next need | Relevant skills |
| --- | --- |
| Clarify requirements and organize approved work | `review-spec`, `plan`, `create-issue` |
| Implement a recorded issue or isolate its checkout | `implement-issue`, `create-worktree` |
| Examine or change the filter interface | `design-ui`, `implement-ui`, `review-ui`, `sync-design` |
| Check code and test the requested behavior | `review-code`, `qa` |
| Record a commit or prepare a pull request | `commit`, `create-pr` |
| Review, respond to, or follow a pull request | `review-pr`, `pr-feedback`, `watch-pr` |

The complete inventory and each procedure's inputs are in the [skill reference](../contributing/skills-reference.md). That reference also covers dependency review and updates, documentation, project status, and evaluation of Neurath's own working support, or harness. You do not need to memorize the inventory before asking for work.

## Say how far the request should go

“Find the cause” and “fix and verify it” authorize different results. State whether the agent should stop at an explanation, make the change, or also prepare review material. For a longer authorized sequence, `autopilot` helps carry work through its applicable stages; it does not create permission for unrelated work or public actions.

Some installations add a prefix to skill names to avoid collisions with existing skills. Ask which installed name applies instead of guessing from a source directory name. Changing an installed prefix requires uninstalling that installation first; a prefix does not resolve competing harness authority. An installed procedure does not override current user instructions, repository rules, or host permissions.

## Leave the next conversation enough to continue

Before pausing the filter investigation, you can ask:

> Save the confirmed cause, the changes made, the checks actually completed, and what remains to prove after refresh so another session can continue.

`checkpoint` supports a retained handoff report. `finish-session` helps close the current working session with the actual state recorded; unfinished user work must remain visible. `memory-to-rules` is for an authorized proposal or promotion of reusable guidance and has a separate review boundary. [Returning to work](memory.md) explains how those records differ from completed tasks and validated learning.

When the investigation would benefit from an independent API or browser check, see [working with other agents](agents.md).

[한국어](../../ko/usage/skills.md)

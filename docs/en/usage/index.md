# Using Neurath in your project

**English** · [한국어](../../ko/usage/index.md)

<!-- date: 2026-09-07; synced_from: source and documentation at 2456ae73ffaf818c04ea4419574218df36852805; English and Korean editions updated together -->

[Usage](index.md) · [Contributing](../contributing/index.md)


Use this guide when you want Claude Code or Codex to work on **your own project** with shared
memory, coordinated agents, and recorded checks. You provide the task and project conventions;
Neurath connects the agent's work to them. To change Neurath's installer, hooks, or skills,
start with [contributing](../contributing/index.md).

## 1. Install and connect the project

From the downloaded Neurath source directory, run:

```sh
./setup /absolute/path/to/your-project
```

You need macOS or Linux, Git, and an authenticated Codex or Claude Code installation. Setup
prepares Python 3.14 and Neurath in an independent environment. Your project's language,
dependencies, and `.venv` remain its own. See [installation](installation.md) for host selection,
skill prefixes, previews, updates, and removal.

Open the target project in your host, review the installed hooks, and start a new session.
Then ask the agent:

> Read this project's instructions and `.neurath/project.json`. Connect its existing product
> documentation and check command. Explain what that check covers and ask me only for missing information.

The bindings identify your documents and the checks that count for **this project**. A successful
installation does not mean its tests or native host activation have been verified. Review
`.neurath/project.json` with the agent before starting a task. [Project bindings](profiles.md)
explains what is configurable.

## 2. Start with an outcome and constraints

Describe the expected result, the current problem, and any boundaries. For example:

> Retrying work log export creates duplicate rows. Reproduce the problem, fix it without
> changing the export format, and verify it with this project's tests. Report the changed files,
> checks run, and any remaining uncertainty.

The agent chooses a skill using the task's purpose and available evidence. You can also invoke
a skill explicitly. If you installed a `neurath-` prefix, use names such as `/neurath-debug`.

| What you want to do | Starting point | What to provide |
| --- | --- | --- |
| Clarify a feature before implementation | `/plan`, then `/review-spec` | Desired behavior, constraints, and existing specifications |
| Fix a reproducible problem | `/debug` | Steps, expected and actual results, relevant error output |
| Implement an approved issue | `/implement-issue` | The issue and its acceptance conditions |
| Understand or review code | `/explain-code`, `/review-code` | Files or changes to inspect and the question to answer |
| Verify behavior in the running product | `/qa` | A scenario, environment, and expected visible or stored results |
| Finish a change | `/finish-session` | Which delivery actions are authorized, such as commit or PR creation |

These are different starting points, not a sequence required for every task. The
[skill catalog](skills.md) lists the available roles. Installation does not authorize the agent
to publish changes or change project permissions.

## 3. Review the result and its evidence

After configuring a `check` binding, you or the agent can run this from the target project:

```sh
.neurath/run verify check
```

It runs the project's configured command, working directory, success conditions, and timeout.
A successful exit code is insufficient if the command changes repository files during verification.
If no `check` is configured, bind a real command first; no check is inferred from the tools installed.

At handoff, look for the changed behavior, checks actually run, review findings, and remaining
limitations. Test results, another agent's report, and a pushed commit establish different facts.
A task that requires independent review still needs that review; a passing test does not replace it.

## 4. Continue work and coordinate agents

In a later session, make the next outcome explicit:

> Continue the work log export fix. Read the saved decisions and remaining work, compare them
> with the current code, and complete the pending verification.

Active hooks save work records and recall relevant project memory. The agent leaves a concise
handoff at the end of command work. You can inspect relevant records and learning status:

```sh
.neurath/run memory recall --query "work log export"
.neurath/run learning status
```

Memory is shared within the same local Git repository and linked worktrees. Separate clones
and computers do not share it automatically. A saved decision is context, not renewed permission.
[Memory and learning](memory.md) explains what is retained and how verified recovery guidance evolves.

For parallel work, give tasks distinct responsibilities and use separate worktrees for edits.
Ask the agent to consult a peer or another provider when that helps the task. Newsroom shares
headlines with active peers; each retrieves relevant details. See [agent collaboration](agents.md)
for commands, delivery states, and provider requirements.

## When something does not work

| Symptom | Next step |
| --- | --- |
| `neurath` is not found | Use the full executable path printed by setup, or `.neurath/run` in an installed project. |
| Skills or hooks do not appear | Check the selected host, installed prefix, project trust, and hook loading; start a new session. |
| Setup reports a conflicting file | Preserve the file and reconcile its contents using the installation plan. Review [updates and recovery](installation.md); do not force an overwrite. |
| Verification has no binding | Configure the project's actual command in `.neurath/project.json` before running it. |
| A peer has not acknowledged a message | Check its delivery state. Queued or submitted does not mean received; an inactive session is not automatically awakened. |
| A fresh session has little context | Confirm this is the same local repository or a linked worktree and that hooks were active when records were created. State the missing context explicitly. |

For local installation diagnostics, run:

```sh
.neurath/run doctor --protocol
```

This checks installation placement and hook protocol behavior. Actual host trust and activation
must still be checked in the host. If reporting a problem, include the command, expected and
actual behavior, Neurath and host versions, and a minimal reproduction. Remove personal paths,
credentials, and private content from excerpts; do not upload installation plans or local state.

[Installation](installation.md) · [Project bindings](profiles.md) · [Skills](skills.md) ·
[Terminology](../terminology.md) · [Contributing to Neurath](../contributing/index.md)

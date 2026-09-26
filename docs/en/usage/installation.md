<!-- updated: 2026-09-19 | synced_from: 243400e58ca74c7fd79bcdd86b488953fa743b97 -->

# Prepare the agent before the investigation

Before asking an agent to fix a disappearing saved filter in your web application, make sure Neurath is connected to the repository where that work will happen. Neurath adds working instructions, reusable procedures, and event handling to Claude Code or Codex. The application that runs the agent is called its **host**.

Open your project folder in Codex or Claude Code and send the request below.

> Read the installation documentation at https://github.com/E5presso/neurath and install Neurath in the current project for Codex and Claude Code. If this is not yet a Git repository, initialize it first. Preserve existing instructions, hooks, permissions, and the development environment, and connect the project's documentation and test commands. After installation, verify that hooks and MCP tools are active in a new session, and tell me about any trust approvals I need to complete myself.

You can name just one host. The agent checks that the target is a Git repository on a supported macOS or Linux system and prepares Neurath's separate runtime, which currently requires Python 3.14. Your application's language and dependencies do not need to match it. Host sign-in and project trust still belong to the host; installation does not supply credentials or approve trust on your behalf.

## See the proposed change before it is applied

The agent inspects existing project guidance and settings, then prepares an installation plan. Ask to see the preview if you want to review the affected files first. Existing instructions, permissions, and project dependencies are preserved. Neurath also preserves **hooks**, the host's event handlers that run when a session starts, a tool finishes, or another supported event occurs.

A file already using a managed name, or a Neurath-managed file that has been edited, can make installation or an update conflict. The agent should identify the conflicting content and resolve it within your request. A successful plan does not justify overwriting it silently.

The agent connects existing project documents and checks so later work can follow your repository's own standards. If a needed decision or test is missing, the result should name that gap. [Project conventions](profiles.md) explains what this connection provides.

## Ask what is actually active

A useful installation result separates four observations:

- The planned files were placed in the repository.
- Neurath's installed runtime can execute.
- A real event from the chosen host reached Neurath's hooks.
- The current host connection can use Neurath's tools.

Those tools are exposed through **MCP**, the connection protocol the host uses to call Neurath. A host that was already open can retain an older connection after the files change. Ask the agent to reconnect or use a fresh host session when needed, and verify the result there. Whether it can restart the host for you depends on the controls that host exposes.

This is also where the agent may ask once whether common Neurath problems may be reported publicly. You can decline or leave the question unanswered and still use Neurath. See [reporting choices](reporting.md).

## Keep the installation current

During active work, supported hooks can remind the agent that a release check is due. The agent can then check for a stable release and present an update notice; the hook itself does not make a network request or start another session. Routine checks are spaced at least a day apart, and you can request a fresh check. A notice does not install the update. A failed network check leaves availability unknown and does not stop your original task.

> Run the `update-neurath` skill in this project. Show the available release and its effect on this installation, apply the version I choose, and verify the active host connection afterward.

One skill invocation carries the check, exact preview, choice, application, and result readback. The agent pauses for your decision on the prepared version; invoking the skill does not approve an unseen change.

The choice applies to the prepared release. If that preview changes, the agent needs a new choice. A version you postpone stays deferred. Updates continue to preserve project bindings and local settings; changed managed content remains a conflict to resolve.

## Recover or remove it when needed

You can ask the agent to recover an interrupted installation, restore an earlier installation, or uninstall Neurath. Recovery uses the recorded operation state. Restoration and removal preserve unrelated edits and user-edited project bindings. Local installation history and empty directories can remain, so removal is not a promise to erase every local record.

After preparation, return to [the first investigation](start-here.md). Agents needing executable installation instructions should use the [installation reference](../contributing/installation.md), [setup reference](../contributing/setup-reference.md), and [release reference](../contributing/releases-reference.md).

[한국어](../../ko/usage/installation.md)

## If the harness malfunctions

The agent can temporarily switch off Neurath on its own when it detects a harness malfunction; you do not need to approve that recovery switch. It should tell you why, preserve unfinished work, and restore the harness after checking the recovery. This applies to abnormal harness behavior generally, including contradictory instructions, unproductive repetition and interference with stopping. Host security and your instructions remain in force.

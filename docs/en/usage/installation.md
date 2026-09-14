<!-- date: 2026-09-14; synced_from: 655c8768709e59b5e5012bab0adc4d888e3e7fa5 + current working-tree facts -->

# Install, update, or restore Neurath

[한국어](../../ko/usage/installation.md)

Ask the agent to install Neurath in the Git project where you want to work. It inspects the existing setup, preserves the project's settings, and connects the documents and checks already used there.

> Install Neurath here for Claude Code and Codex. Keep my existing instructions and hooks, use this project's real checks, and tell me when it is ready to use.

## Get the first session ready

You need macOS or Linux, Git, and Claude Code or Codex. Neurath requires Python 3.14; the quick installer can provision it. The initial defaults use the generic profile and both hosts. You can ask to install for just one host.

The agent prepares the integration and checks what it can. You may then need to log in, accept the host's trust prompt, start a new session, or reload its tool catalog. The result should identify the remaining action, for example: “Files are installed for Codex. Start a new session so the integration can be checked there.”

If your project already has a harness or similarly named skills, ask the agent to inspect their overlap before installing. A skill prefix can resolve a name collision; responsibility for shared hooks and state still needs to be clear.

## Keep the project's existing setup

Installation preserves existing instructions, hooks, permissions, your edited project bindings, project dependencies, and the project's virtual environment. Neurath uses a separate runtime environment. Updating one project leaves other projects on their installed runtime, and previous runtimes remain available for restoration.

If a managed file has been edited manually, the agent shows the conflict. Installation plans and backups can contain private configuration, so they stay local.

As part of setup, the agent connects real documentation and verification routines. If a needed document or check is missing, it explains what is absent and which decision it needs from you. See [Connect Neurath to your project](profiles.md).

## Decide when to update

> Check for an official stable update, prepare the change, and explain what it would affect before applying it.

During active work, Neurath checks for official stable releases at most daily unless you ask again. An update notice gives the installed and offered versions, material changes, and an official link. It does not start a separate session or apply the update automatically.

The agent prepares the proposed update before asking for your choice. An explicit yes applies to that prepared offer. No answer leaves the installation unchanged. If you decline or postpone a version, it stays deferred until you resume it. The choice carries across sessions, and updates preserve your reporting and contribution consent.

A failed release check does not interrupt your original task. If an earlier update was interrupted, ask the agent to inspect the installation and prepare a recovery before trying to apply it again.

An update changes the installed files, but an already-running tool connection may still use the older version. If new tools or behavior are missing, ask the agent to reconnect the affected MCP connection and verify the active version. A successful on-disk update alone does not show that an existing connection has reloaded it.

You can also ask:

> Save the current work, restart the app if needed, and continue this same task without asking me to operate the machine.

When the host provides scheduling and an independent restart mechanism, the agent can prepare both before closing the app. Neurath preserves the task history and work ownership; after returning, the agent checks the new connection and continues the unfinished work. The agent verifies that the restart mechanism actually runs, protects other active work, and stops the continuation schedule after it has served its purpose. App restart remains a host operation, and its available controls determine whether this route can run unattended.

## Restore or remove an installation

> Restore this project's previous Neurath installation, preserve my changes, and check the restored integration.

You can also request an update preview, installation in another project, recovery of an interrupted installation, or removal of the managed integration. The agent uses the installation history to work out what can be restored while preserving your edits.

After removal, empty directories, installation history, and user-edited project bindings may remain. The result should explain what was removed and what was retained.

Continue with [Working with Neurath](index.md). Detailed runtime requirements, update validation, installation records, and executable procedures are in the [contributor documentation](../contributing/index.md).

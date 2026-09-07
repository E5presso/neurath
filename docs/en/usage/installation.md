# Installation and maintenance

**English** · [한국어](../../ko/usage/installation.md)

<!-- date: 2026-09-07; synced_from: source and documentation at e1487a1718056b37b999d1343a1007b7e25f5c8c; English and Korean editions updated together -->

[Usage](index.md) · [Contributing](../contributing/index.md)

**Ask your agent to install and maintain Neurath.** It reads the
[installation execution reference](../contributing/setup-reference.md), inspects the target
project, and performs the necessary operations. This guide explains what to request and expect.

## Install in a project

> Install Neurath from https://github.com/E5presso/neurath in this project. Preserve existing
> instructions, hooks, permissions, skills, and dependencies. Connect our actual documentation
> and verification procedure, check the installation, and explain any host action I must take.

The supported environment is macOS or Linux with Git and Codex or Claude Code. The agent
checks prerequisites; quick setup prepares Python 3.14 and an independent Neurath environment.
It preserves the target project's dependencies and development environment.

The initial defaults are the generic profile and both hosts. If you only use one host, say so.
The agent handles installation options and existing skill names. If a name conflict requires
a prefix, it can install Neurath skills under distinct names while preserving existing skills.
A prefix resolves names; overlapping responsibilities with another harness still require review.
The agent explains any unresolved conflict before proceeding.

## Connect your existing project

> Use this project's existing requirements, architecture decisions, and tests. Find the relevant
> files and check procedure; ask me only when the intended source or command is unclear.

The agent records those connections in the project configuration. You do not need to edit it.
Updates preserve user-edited bindings. An unconfigured check remains unverified; installation
does not invent the project's test procedure.

## Confirm the result

Ask the agent to distinguish these results:

| Result | What it establishes |
| --- | --- |
| Installation and local diagnostics | Managed files, distribution integrity, and hook protocol checks |
| Project verification | The project's actual check ran under its configured success conditions |
| Host activation | Installed hooks and tools function in the actual Codex or Claude Code session |

The installer cannot approve host trust or log in for you. Complete any required authentication
or trust decision in the host, following the agent's explanation. A new session may be needed
to load the installed integration. Local diagnostics alone do not prove host activation.

## Update, remove, or recover

| Your goal | Request to the agent |
| --- | --- |
| Preview changes | “Inspect the proposed Neurath installation changes and summarize them before applying.” |
| Update this project | “Update Neurath in this project, preserve our changes, and verify the result.” |
| Install in another project | “Install Neurath in this target project with its own documentation and checks.” |
| Remove Neurath | “Remove Neurath's managed integration while preserving our files and edits.” |
| Undo an installation change | “Inspect the installation history and restore the previous installation state.” |
| Recover after interruption | “Inspect the interrupted installation and recover it without discarding existing content.” |

Updates apply to the selected project; other projects retain their installed runtime.
Previous runtime environments support restoration. The agent inspects installation records
and conflicts before recovery. Edited managed content can stop an update or removal, and an
incomplete tool environment can stop setup. These conditions require diagnosis, not forced
overwriting. Removal may leave empty directories and change history.

Installation plans and recovery records stay local because they can contain original project
settings. For technical implementation and command details, agents use the
[setup reference](../contributing/setup-reference.md) and
[installation development guide](../contributing/installation.md).

[First task](index.md) · [Project bindings](profiles.md) · [Skills](skills.md)

<!-- date: 2026-09-13; synced_from: 655c8768709e59b5e5012bab0adc4d888e3e7fa5 + current working-tree facts -->

# Use the project's existing documents and checks

[한국어](../../ko/usage/profiles.md)

Neurath works best when the agent knows which documents explain your project and which checks establish that a change works. Ask it to inspect what is already there and connect the relevant material.

> Use this project's existing architecture notes and verification routines. Keep our terminology and working conventions. Ask me about any decision you cannot establish from the repository.

The agent maintains the project bindings for you. The current profile is generic; the project's instructions supply its language, framework, tools, and conventions.

## Connect a document to the work it explains

Suppose architecture decisions and contributor guidance already exist. Ask the agent to use them for implementation and review. It identifies the documents that serve those purposes and shows you any missing role. If there is no suitable document, the gap remains visible so you can decide what information is needed.

This also preserves the project's glossary and writing language. The agent follows the existing branch, commit, and issue conventions rather than asking you to define them again during installation.

## Establish a meaningful check

> Find the check used for this part of the project and connect it. Tell me what it covers and whether you were able to run it.

The agent identifies the actual check, where it runs, and how the project recognizes success. The result tells you what was checked and whether it passed. When a check is missing, unavailable, or restricted, you see that limitation and its effect on the requested work.

You supply only the missing decision—for example, which of two existing project checks should govern this work. You do not need to edit Neurath's configuration yourself.

## Keep the connection current

When documents move or the project's check changes, ask the agent to update the connection. Your edited bindings remain yours across updates and removal. Existing instructions, permissions, dependencies, and the project environment are preserved during installation.

For a project that uses external services or needs protected paths, describe the intended resources and access boundaries. The agent checks the actual setup; installing Neurath does not automatically protect every external service. The [contributor documentation](../contributing/index.md) details document roles, verification settings, connector bindings, metadata conventions, and the default protection of harness resources.

Continue with [task requests](index.md), or use [Installation and maintenance](installation.md) when a setup change requires recovery or restoration. [Terminology](../terminology.md) explains Neurath's record names without replacing your project's domain vocabulary.

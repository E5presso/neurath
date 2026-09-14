<!-- date: 2026-09-14; synced_from: 655c8768709e59b5e5012bab0adc4d888e3e7fa5 + current working-tree facts -->

# Neurath

[한국어](README.ko.md)

Neurath is a harness for Claude Code and Codex that brings project instructions, task tracking, verification procedures, and shared memory into an existing Git project. It helps agents carry a request through implementation and checking, retain useful context between sessions, and coordinate work without making you repeat the project's working practices each time.

Its central strategy is to help the agent reconsider its approach as work proceeds. Periodic reminders bring the original goal and acceptance conditions back into view, so the agent can replace an unproductive method without dropping the requested work.

Neurath works with the project's own language, framework, documents, and tests. You describe the outcome you want; the agent uses the relevant procedure and reports what changed and what it checked.

## What it brings to your project

- **Project-aware work.** The agent follows your existing instructions and uses the documents and checks connected to the project. A bug fix can start with a reproduction and end with a test result that addresses the reported behavior.
- **Tasks that survive a change of focus.** Measurable tasks record the original request, dependencies, and results. A side question adds context while unfinished work remains visible.
- **Continuity between sessions.** Local memory retains observed decisions, results, and remaining work. A later session can retrieve that history and compare it with current source before continuing. If a provider stops because its quota is exhausted, another provider can pull the saved context and adopt unfinished work once the source has stopped safely.
- **Coordinated agents.** Agents in linked worktrees can exchange findings and work independently in separate workspaces. When a task needs another provider, the agent checks whether that session can carry out the assignment with the requested model and permissions. You can ask the receiving provider to retain its own native settings.
- **Installation that fits around existing work.** Neurath preserves project instructions, hooks, permissions, dependencies, and the project's virtual environment. Its runtime lives separately, and installation records support updates and restoration.

## Start with a request

Open your project in Claude Code or Codex and ask:

> Install Neurath in this project from https://github.com/E5presso/neurath. Preserve my existing instructions and settings, connect the project's documents and checks, and confirm that it is active in this session.

The agent inspects the project, prepares the integration, installs it, and checks the result. If the host needs login, project trust, or a new session, the agent explains that specific next step. Installed files and successful diagnostics are reported separately from actual host activation.

Neurath supports macOS and Linux, with Git and Claude Code or Codex. Its installer provisions Python 3.14 for the harness. The default integration supports both hosts; you can request just one. See [installation and maintenance](docs/en/usage/installation.md) for host choices, updates, restoration, and removal.

## Use it for the work in front of you

You do not need to remember skill names. Give the agent the outcome, constraints, and any evidence you already have:

> Find why this test fails, reproduce the problem, and fix it. Explain the behavior that changed and the checks you ran.

> Review this change for defects. Include the affected code and a concrete failure scenario for each finding.

> Continue the unfinished work from the previous session. Check that the recorded decisions still match the current source.

> Have a separate agent review the API contract while you implement the approved issue in your own worktree.

Neurath also includes procedures for planning, specification review, UI design and implementation, deployed-system QA, dependency maintenance, and authorized delivery. [Choose a task](docs/en/usage/skills.md) shows how to ask for each kind of work. Requests to publish a change or alter permissions remain subject to your instructions; installing Neurath does not grant that authority.

## Find the right guide

Start with the [usage guide](docs/en/usage/index.md) to learn how to request work and read its results. Continue with [working with agents](docs/en/usage/agents.md) for collaboration, [memory](docs/en/usage/memory.md) for continuity, and [reporting](docs/en/usage/reporting.md) for optional contributions to Neurath.

To change Neurath itself, use the [developer guide](docs/en/contributing/index.md). It covers the source layout, installation contracts, runtime APIs, and validation procedures. [Terminology](docs/en/terminology.md) connects the words used in these guides to exact names in tools and source.

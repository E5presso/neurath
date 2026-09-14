<!-- date: 2026-09-14; synced_from: 655c8768709e59b5e5012bab0adc4d888e3e7fa5 + current working-tree facts -->

<p align="center">
  <img src="docs/assets/neurath.png" width="720" alt="Neurath's boat, repaired while still at sea">
</p>

<h1 align="center">N E U R A T H</h1>
<p align="center"><strong>Keep the context. Stay the course.</strong></p>
<p align="center">A harness for Claude Code and Codex.<br>Shared memory, thoughtful collaboration, and a clear path back to your goal.</p>
<p align="center"><strong>English</strong> · <a href="README.ko.md">한국어</a></p>
<p align="center"><a href="#start-with-a-request">Get started</a> · <a href="docs/en/usage/index.md">Usage guide</a> · <a href="docs/en/contributing/index.md">Contributing</a></p>

---

A new session should not mean starting over. Neurath helps your agents carry decisions forward, share what they learn, and return to the work you actually asked for.

### Remember. Reconsider. Continue.

- **Remember the work.** Carry decisions and unfinished tasks between sessions—even when you switch between Codex and Claude.
- **Keep your bearings.** Bring the original goal back into view, so an agent can change its approach without losing the purpose.
- **Build together.** Let agents exchange findings and review one another's work while keeping editing responsibilities separate.

The name comes from Neurath's boat: a vessel rebuilt at sea, without a chance to start from dry land. Software grows the same way. Keep what works, learn from what does not, and improve while the work moves forward.

Your project keeps its language, tools, and working practices. Neurath adds the memory and coordination around them.

## Start with a request

Open your project in Claude Code or Codex and ask:

> Install Neurath in this project from https://github.com/E5presso/neurath. Preserve my existing instructions and settings, connect the project's documents and checks, and confirm that it is active in this session.

The agent handles setup, preserves your existing settings, and reports whether Neurath is active. If login, project trust, or a new session is needed, it tells you exactly what remains.

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

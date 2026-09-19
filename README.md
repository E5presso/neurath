<!-- last_updated: 2026-09-19; synced_from: 243400e58ca74c7fd79bcdd86b488953fa743b97 -->

<p align="center">
  <img src="docs/assets/neurath.png" width="720" alt="Neurath's boat, repaired while still at sea">
</p>

<h1 align="center">N E U R A T H</h1>
<p align="center"><strong>Keep the context. Stay the course.</strong></p>
<p align="center">A harness for Claude Code and Codex.<br>Shared memory, thoughtful collaboration, and a clear path back to your goal.</p>
<p align="center"><strong>English</strong> · <a href="README.ko.md">한국어</a></p>
<p align="center"><a href="docs/en/usage/start-here.md">Get started</a> · <a href="docs/en/usage/index.md">Usage guide</a> · <a href="docs/en/contributing/index.md">Contributing</a></p>

### Install in your project

On macOS or Linux, open your project folder in Codex or Claude Code and send this request:

> Read the installation documentation at https://github.com/E5presso/neurath and install Neurath in the current project for Codex and Claude Code. If this is not yet a Git repository, initialize it first. Preserve existing instructions, hooks, permissions, and the development environment, and connect the project's documentation and test commands. After installation, verify that hooks and MCP tools are active in a new session, and tell me about any trust approvals I need to complete myself.

If you use only one host, replace “for Codex and Claude Code” with “for Codex” or “for Claude Code.” See the [installation guide](docs/en/usage/installation.md) for the installation process and activation checks.

### Remember. Reconsider. Continue.

- **Remember the work.** Carry decisions and unfinished tasks between sessions—even when you switch between Codex and Claude.
- **Keep your bearings.** Bring the original goal back into view, so an agent can change its approach without losing the purpose.
- **Build together.** Let agents exchange findings and review one another's work while keeping editing responsibilities separate.

Neurath is a technology-independent harness: a supporting layer around Claude Code and Codex that helps an agent carry a development task through investigation, collaboration, and a change of session.

Its name comes from Otto Neurath's image of repairing a ship while still at sea. The work continues while its parts change; the destination stays in view.

**[Follow one bug from request to verified fix](docs/en/usage/start-here.md).** Start with a hypothetical web app whose saved filter disappears after refresh, and learn each idea when the agent needs it. To apply it to your Git project, [ask your agent to prepare installation](docs/en/usage/installation.md).

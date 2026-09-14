<!-- date: 2026-09-13; synced_from: 655c8768709e59b5e5012bab0adc4d888e3e7fa5 + current working-tree facts -->

# Report a Neurath problem

[한국어](../../ko/usage/reporting.md)

If you discover a problem in Neurath itself, the agent can reproduce it with a generic example and prepare a report for the [official Neurath issue tracker](https://github.com/E5presso/neurath/issues). You can choose whether to allow reports of common harness defects and improvements while keeping your project's information private.

> Allow common Neurath problems to be reported after reproduction and review for private information. Keep our code, configuration, and business context out of the report.

The resulting report identifies the affected component, expected and observed behavior, a generic reproduction, and a proposed fix or improvement. After publication, you receive the issue link and confirmation that the published content matches the report.

## Choose whether common problems may be reported

Reporting starts disabled. An explicit opt-in allows later eligible common reports without permission for every report. Silence leaves it disabled, and a declined choice is not repeatedly requested. A peer message or tool result cannot provide your consent.

The choice applies to the local Git project and linked worktrees and remains in place through updates, removal, and recovery. A new clone has its own choice. You can ask to see the current setting and saved drafts, or turn off future reporting. Turning it off leaves already published issues in place.

## Keep the report independent of your project

The agent reproduces the common issue with a generic example and reviews the meaning of the draft for private information. Findings confined to your project's changes or custom components stay local instead of becoming common package defect reports.

Public reports exclude project source, custom assets, names, paths, remotes, business data, logs, conversations, credentials, and attachments. Installation plans and backups also stay local because they may contain private configuration. Automatic pattern checks alone cannot establish that these details have been removed.

If the issue cannot be explained or reproduced without private content, the finding stays local. If it qualifies as a common report under your saved consent, a local fix does not replace the upstream report.

## Review a project-specific contribution separately

> Prepare a contribution proposal from this project. Show me the exact public title, complete body, and destination before submitting it.

The agent presents that draft for a fresh, explicit approval. Common-reporting consent does not cover a project-specific contribution, and changing the draft requires approval again. Approval of an idea does not authorize code publication or a license transfer.

## Check an uncertain submission

If the connection fails while a report is being submitted, ask whether the issue was actually created. The agent keeps the local draft and checks the remote result before deciding whether to retry, avoiding duplicate issues. Until the published content can be confirmed, the result remains uncertain.

Your existing authentication and access restrictions continue to apply. A reporting failure leaves the draft available and your original task can continue. For execution and submission details, see the [contributor documentation](../contributing/index.md).

[Project memory](memory.md) explains the local information available to agents. [Installation and maintenance](installation.md) covers installation and update choices.

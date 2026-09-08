# Reporting harness improvements

**English** · [한국어](../../ko/usage/reporting.md)

During installation, the agent asks whether it may report defects and improvements in the
common Neurath harness to the [public Neurath issue tracker](https://github.com/E5presso/neurath/issues).
No answer means reporting stays disabled. Your explicit choice stays with this local Git
project across updates and its worktrees; a new clone requires its own consent.

> Enable automatic reporting of common Neurath harness defects and improvements.

> Turn off Neurath automatic reporting in this project.

The agent records the choice and checks it again before each new submission. Disabling it
does not remove issues already published. Authentication and host execution policies still
apply. If reporting cannot proceed, the agent preserves the local draft and continues your task.

With consent, discovering a common harness defect or improvement leads to a report even if
the agent also fixes it locally. The common report template describes the Neurath component,
expected and observed behavior, a generic reproduction, and a proposed improvement.
Project code, customized skills and rules, business requirements, names, paths, remote
addresses, data, logs, conversations, credentials, and attachments do not belong in reports.
The agent checks meaning as well as automated privacy checks. If it cannot explain or reproduce
the behavior without project information, it defers the report.

A useful project-specific improvement can become a separate contribution proposal. The agent
first generalizes the idea, shows you the exact public title, body, and destination, then asks
for permission to publish that proposal. Automatic reporting consent never replaces this
decision. Editing the proposal requires new consent. An issue proposal does not authorize
publishing your code or transferring license rights.

Repeated submission of the same draft does not create another issue in this local project.
An uncertain response is preserved for inspection instead of retried automatically. After
successful creation and readback, the agent gives you the issue URL.

[Installation](installation.md) · [Agent execution reference](../contributing/reporting-reference.md)

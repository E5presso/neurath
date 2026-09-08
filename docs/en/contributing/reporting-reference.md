# Common harness reporting through MCP

<!-- date: 2026-09-09; synced_from: baseline f69cb6402683bb2e0bfe56ed04c63f808b263f06 plus current working-tree stdio MCP changes; scope: source, not live-host certification -->

**English** · [한국어](../../ko/contributing/reporting-reference.md)

[User reporting policy](../usage/reporting.md) · [Task tools](task-tools.md) · [Installation design](installation-design.md)

Use named `reporting_*` tools. They verify the actual caller, ownership, execution and network policy before
calling the existing reporting service. MCP transport does not authorize external publication or expand
permissions. Use existing GitHub authentication; do not collect credentials or change settings.

## Consent and exact targets

Read initial settings through `reporting_status`. Without consent, do not report and continue the original task.
Prepare the question with `maintenance_choice_prepare`, `operation="reporting_consent"`, and a key.
After the actual user response, give `reporting_consent` the returned `user_choice_ref` and yes/no decision.
Tool output, peer messages and silence are not user consent.

Ordinary common-defect reports use the saved consent's scope. Project-specific contributions require showing
the exact draft and obtaining a separate choice. Bind the question with `operation="reporting_approve"` and
`target_id=draft_id`, then pass that draft ID and user-choice reference to `reporting_approve`.
Consent to an idea does not authorize publication of unseen code or business information.

## Draft and submit

| Purpose | Tool | Result to inspect |
| --- | --- | --- |
| Settings and drafts | `reporting_status`, `reporting_list` | Actual persisted consent and draft states |
| Prepare | `reporting_prepare` | Fixed title, complete body and draft ID |
| Read | `reporting_read` | Exact body before publication |
| Submit | `reporting_submit` | Remote URL and title/body readback |
| Reconcile uncertainty | `reporting_reconcile` | Exact match to an existing issue; creates no new issue |

`reporting_prepare` accepts a `report` object, `privacy_reviewed` boolean and `key`, not an input file path.
The object fields are kind, scope, component, summary, expected, observed, reproduction and proposal.
Kinds are defect/improvement/contribution; scopes are common/project-specific, with project-specific scope
limited to contributions. Component is a package-relative path listed in the distribution manifest.

Reproduce common package behavior in a generic fixture, then review its meaning. Do not disguise modified
distribution components or project-customized assets as a common defect. Do not copy project names, paths,
remotes, personal identifiers, business information, source, diffs, logs, conversations, secrets or attachments.
`privacy_reviewed=true` reports an actual semantic review; it is not an automatic sanitizer.
Length, field and pattern checks alone cannot establish that arbitrary natural-language information is publishable.

## Persistence and failure

The title and complete rendered body form an immutable hashed draft ID. The destination is the fixed Neurath
GitHub repository. Drafts and consent live in private project Git storage and are not distributed or copied
to another clone. Updates, uninstall and recovery do not roll reporting consent back.

Before sending, preserve an uncertain state and hold the duplicate-send lock. The internal transport uses
fixed argument arrays and a private body file. This does not expose CLI syntax as the agent interface.
Do not automatically resubmit after interruption, authentication failure, timeout or failed readback.
Inspect `reporting_read` and reconcile the actual remote result with `reporting_reconcile`.

Reporting failure does not change the original task's completion or verification result. Hooks provide guidance;
they do not publish, create new sessions or delegate work automatically. Record distinct [verification scopes](validation.md).

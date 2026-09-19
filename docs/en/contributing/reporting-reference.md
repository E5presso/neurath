<!-- date: 2026-09-14; synced_from: 243400e58ca74c7fd79bcdd86b488953fa743b97 -->

# Prepare a useful public harness report

[한국어](../../ko/contributing/reporting-reference.md) · [Contributor entry](index.md)

A public Neurath report should explain a defect or improvement in the shared harness without disclosing the user's project. The user's application bug remains their task. For example, a saved filter disappearing after refresh is not automatically a Neurath defect; only a separately observed harness problem belongs in this reporting route.

Reports go to the fixed [E5presso/neurath issue repository](https://github.com/E5presso/neurath/issues). Common defects and improvements require the project's saved explicit reporting consent. A contribution, including a proposal derived from project-specific changes, requires approval of its exact public draft. Setup and hooks can remind the agent about this choice; hooks do not collect or send reports.

## Establish the reporting choice

Read `reporting_status` with `{}`. `auto_report` is `null` while consent is pending, `false` when declined, and `true` when enabled. Pending consent leaves automatic reporting disabled and does not block the user's original task. A fresh clone does not inherit this private choice.

To obtain the native question, call `maintenance_choice_prepare`:

```json
{"operation": "reporting_consent", "key": "reporting-question-1"}
```

Show its exact question, then wait for the actual user response. The returned `user_choice_ref` identifies the question and its subject. A native **receipt** is a retained host record establishing that the user answered it. An agent-authored “yes” or a copied reference is not that record. With the real answer, use `reporting_consent`:

```json
{"decision": "yes", "user_choice_ref": "RETURNED_USER_CHOICE_REF", "key": "reporting-consent-1"}
```

Send the returned question as the entire final assistant message, without introductory or trailing explanation. The supported Claude path is a fresh plain-text user reply; `AskUserQuestion` tool results do not produce the required prompt receipt. Common replies such as `yes`, `네`, `동의합니다`, `ok`, `no`, and `아니요` are recognized. Errors distinguish a changed question from an unsupported answer.

Use `no` for a decline or revocation. Reporting state uses canonical private `LocalState`/SQLite storage; old reporting JSON is migration input, not a second current authority.

## Write and inspect a bounded draft

`reporting_prepare` takes `report`, `privacy_reviewed:true`, and a stable `key`. The report has exactly eight fields:

```json
{
  "report": {
    "kind": "improvement",
    "scope": "common",
    "component": "reporting.py",
    "summary": "Make retained draft status easier to explain",
    "expected": "The agent can describe whether a public report was delivered.",
    "observed": "The status wording can require an additional explanation.",
    "reproduction": "Inspect a prepared draft and the corresponding status response.",
    "proposal": "Describe the meaning of each retained delivery state."
  },
  "privacy_reviewed": true,
  "key": "report-draft-1"
}
```

This is an illustrative draft, not a claim that this defect was observed. Replace it with verified observations before preparing a real report. `component` must name a packaged Neurath file present in the manifest, excluding templates, and its bytes must match the package. A customized installed asset requires a `contribution` rather than a common report.

`kind` accepts `defect`, `improvement`, or `contribution`; `scope` accepts `common` or `project-specific`. Project-specific scope requires contribution kind. Prose fields are nonempty and at most 2,400 characters; `summary` is a single line of at most 140 characters. These service limits are stricter than the generic schema string limit. Logs, attachments, extra fields, unsafe markup, links, paths, credentials, and private remote/project-name patterns are rejected. The checks supplement the agent's semantic privacy review.

Preparation returns an immutable draft ID binding the public title, body, and destination. Read it with `reporting_read` and `{"draft_id":"RETURNED_DRAFT_ID"}`; list retained IDs, statuses, and URLs with `reporting_list`. A content edit requires a new draft and any applicable new approval.

## Approve a contribution, then submit

For a contribution, prepare another native question using `operation:"reporting_approve"` and `target_id` equal to the draft ID. The question contains the exact public draft. After the real reply, call `reporting_approve` with `draft_id`, `decision`, `user_choice_ref`, and `key`. Saved common-report consent does not approve a contribution's contents.

For an authorized common report or an approved contribution, `reporting_submit` takes:

```json
{"draft_id": "RETURNED_DRAFT_ID", "key": "report-submit-1"}
```

Submission serializes across linked worktrees. It saves `uncertain` before network I/O, creates the issue using the fixed repository, then reads the issue back to compare its URL, title, and body. Only that verified result becomes `submitted`. The private temporary body file and explicit destination keep transport independent of the target's GitHub remotes.

## Resolve uncertain delivery without duplicate issues

A connection or authentication failure can happen after the upstream accepted the issue. Therefore a repeated submit on a non-draft returns the retained state instead of sending again. For `uncertain`, inspect the fixed upstream repository and authentication. If the issue exists, use `reporting_reconcile`:

```json
{"draft_id": "RETURNED_DRAFT_ID", "url": "https://github.com/E5presso/neurath/issues/123", "key": "report-reconcile-1"}
```

The URL above is illustrative; supply the actual existing issue. Reconciliation accepts only an issue in the fixed upstream and verifies its exact contents. Mismatched content remains an error. Uncertain delivery does not justify another publication route or automatic resubmission, and it does not change the completion status of the user's original task.

## Terminal forms and diagnostics

```sh
neurath report status
neurath report consent yes --user-confirmed
neurath report prepare PRIVATE_REPORT.json --privacy-reviewed
neurath report read DRAFT_ID
neurath report approve DRAFT_ID yes --user-confirmed
neurath report submit DRAFT_ID
neurath report reconcile DRAFT_ID EXISTING_ISSUE_URL
neurath report list
```

The input file is bounded to 20,000 bytes. The confirmation/review flags record work and decisions that actually occurred. In an installed native session, use the named tools under current policy. Read `invalid reporting state; publication disabled`, `report content changed`, and `upstream issue readback differs from approved report` as concrete state/identity problems to resolve, not invitations to bypass the service.

Source: [report service](../../../src/neurath/reporting.py), [CLI](../../../src/neurath/reporting_cli.py), [native choices](../../../src/neurath/runtime/user_choices.py). Tests: [privacy, concurrency, and delivery](../../../tests/test_reporting.py), [native choices](../../../tests/test_user_choices_mcp.py).

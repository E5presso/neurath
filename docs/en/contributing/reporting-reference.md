<!-- date: 2026-09-13; synced_from: 655c8768709e59b5e5012bab0adc4d888e3e7fa5 + current working-tree facts -->

[한국어](../../ko/contributing/reporting-reference.md)

# Publish a reviewed harness report

Reporting turns a reproducible, generic Neurath finding into an issue at the fixed [upstream issue tracker](https://github.com/E5presso/neurath/issues). The workflow separates permission to publish common findings from permission for a particular project-specific contribution. Reporting hooks provide local reminders; they do not collect content or send reports themselves.

## Consent and destination

`reporting_status` takes `{}` and returns the saved common-reporting choice, whether consent is still required, the fixed repository, and the per-draft contribution requirement. Initial state is undecided and publication remains disabled. An explicit `no` is saved rather than repeatedly asked. The choice is shared by linked worktrees of this Git project, survives updates, and is separate in a new clone.

| Publication | Required choice | Scope |
| --- | --- | --- |
| Generic common defect or improvement | Saved explicit common-reporting consent | Future eligible common findings in this project |
| Project-specific contribution idea | Approval of the exact prepared title, body, and destination | That immutable draft only |
| Source code or other material | Its own publication authorization | Idea approval does not authorize code publication or license transfer |

`reporting_consent` requires `decision` (`yes` or `no`), `user_choice_ref`, and `key`. The reference must identify an actual user choice; do not invent one from silence, peer suggestions, or model preference. `reporting_approve` uses the same fields plus `draft_id` for an unsent contribution draft. Turning common reporting off stops future reports; it does not delete already published issues.

Before recording a new consent answer, call `maintenance_choice_prepare` with `operation="reporting_consent"` and `key`, then bind the actual user reply through `reporting_consent`. For a contribution, first prepare and show the complete draft, then call `maintenance_choice_prepare` with `operation="reporting_approve"`, `target_id` set to its draft ID, and `key`; record the real answer through `reporting_approve`. Tool output and silence cannot supply the user-choice reference.

## Prepare the public text first

The report object has exactly eight fields: `kind`, `scope`, `component`, `summary`, `expected`, `observed`, `reproduction`, and `proposal`. No logs, arbitrary metadata, or attachments are accepted. `kind` is `defect`, `improvement`, or `contribution`; `scope` is `common` or `project-specific`. Project-specific content must use `contribution`.

`component` identifies a packaged Neurath file and must match the package manifest. A common report about a managed asset also checks the installed copy: customization requires a contribution proposal. Keep project code, names, paths, remotes, business facts, conversations, credentials, and custom assets out of the report. Reproduce the finding in a generic fixture and review every field semantically before setting `privacy_reviewed` to `true`.

Example input to `reporting_prepare`, to be used only after reproducing this hypothetical finding:

```json
{
  "report":{
    "kind":"defect",
    "scope":"common",
    "component":"reporting.py",
    "summary":"Report readback fails after a successful issue creation",
    "expected":"A created issue is verified against the prepared title and body.",
    "observed":"The generic fixture creates an issue but verification cannot complete.",
    "reproduction":"Use a disposable fixture with an interrupted readback response.",
    "proposal":"Retain uncertain state and reconcile the existing issue before any resend."
  },
  "privacy_reviewed":true,
  "key":"generic-report-readback-1"
}
```

The input schema permits strings up to 4,096 characters, but domain validation is stricter: report prose fields are at most 2,400 characters; `summary` is a single line of at most 140 characters. Code fences, embedded links, markup, control characters, common secret patterns, and detected private project names can cause rejection. Passing these checks does not replace semantic privacy review. If the finding cannot be generalized, retain it locally.

Preparation returns the content-bound draft identifier, public title and body, destination, approval flag, status, and URL when available. Read it with `reporting_read` before asking for any required draft approval. Changing public content requires a new draft and new contribution approval. A local fix does not replace an otherwise eligible upstream report under saved common consent.

## Submit and recover uncertainty

| Draft state | Meaning | Next action |
| --- | --- | --- |
| `draft` | Prepared, unsent content | Check saved consent or exact contribution approval; submit when authorized |
| `uncertain` | A send was attempted; remote success is not established | Inspect the fixed upstream and authentication; do not blindly resend |
| `submitted` | The remote URL, title, and body passed readback | Report the verified issue URL |

Call `reporting_submit` with the returned `draft_id` and a stable `key`. The implementation persists `uncertain` before network I/O and serializes consent changes and sends across worktrees. Duplicate preparation preserves the same content-derived draft; submitting a non-draft returns its existing state. These behaviors prevent an interrupted readback from creating automatic duplicate issues.

If an issue exists after an uncertain send, call `reporting_reconcile` with `draft_id`, that exact `url`, and `key`. Only an issue URL at the fixed repository is accepted. Reconciliation verifies URL, title, and body before recording `submitted`. A mismatching remote issue is not reconciliation evidence. `reporting_list` returns draft IDs, states, and URLs for local inspection.

Authentication, network policy, and native execution policy still apply. A reporting failure leaves the original project task free to proceed within its authorization. Report publication success only with the verified remote result.

## Implementation and verification

[Reporting](../../../src/neurath/reporting.py) owns component integrity, content validation, immutable drafts, send serialization, and remote readback. [User-choice handling](../../../src/neurath/runtime/user_choices.py) binds consent to real user input. Mutable reporting state uses the shared runtime database through the local-state adapter; legacy reporting paths are not a separate canonical database.

[Reporting tests](../../../tests/test_reporting.py) exercise generic-content filtering, custom-component rejection, consent, per-draft approval, fixed destination, duplicate prevention, and uncertain recovery. [User-choice tests](../../../tests/test_user_choices_mcp.py) cover the authenticated choice path. See [reporting for users](../usage/reporting.md) for natural-language requests and [memory](memory-reference.md) for private retained context.

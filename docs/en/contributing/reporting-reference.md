# Upstream reporting execution reference

**English** · [한국어](../../ko/contributing/reporting-reference.md)

[User behavior](../usage/reporting.md) is the product contract. Native shell commands retain
the current host's ownership, execution, and network policy. Reporting is deliberately not an
auto-approved MCP mutation. Use the existing authenticated GitHub CLI; never change permission
settings or collect credentials to make a report succeed.

Installation agents ask the full question returned by reporting status. On first interactive
setup the installer asks directly; noninteractive setup returns a pending consent question
and installs with reporting disabled. Older installations also receive the onboarding notice.
A missing answer does not become agreement or block unrelated work. Do not repeat a pending
question in the same onboarding conversation; after refusal do not ask again without user intent.

```sh
neurath setup /path/to/project --auto-report yes
.neurath/run report status
.neurath/run report consent no --user-confirmed
```

Pass yes/no only after an explicit user answer. Omit the setup option on updates to preserve
the choice. Dry-run never records it. Consent and drafts live in the Git common directory at
`neurath-reporting/state.json`, outside checkout content; updates, uninstall and restoration
do not roll consent back or copy it into another clone. State writes use a private file,
an atomic replacement, and an interprocess lock. Corrupt settings fail closed.

Prepare a bounded JSON object with exactly these fields:

```json
{
  "kind": "defect",
  "scope": "common",
  "component": "cli.py",
  "summary": "Setup loses an explicit selection",
  "expected": "Setup preserves the selected host.",
  "observed": "A repeated setup resets the host selection.",
  "reproduction": "Use an empty disposable Git repository and repeat setup.",
  "proposal": "Preserve the installed host selection on updates."
}
```

This is an illustrative fixture, not a claim of a current defect. Kinds are `defect`,
`improvement`, and `contribution`. Scope is `common` or `project-specific`; only a
contribution can use project-specific scope, and its content must still describe Neurath alone.
Component is a manifest-listed package-relative path. Common reports reject modified package
components and customized projected assets. This mechanical evidence cannot establish the
semantic cause: the agent must reproduce common behavior using a disposable generic fixture
and verify that the report is about Neurath before asserting the scope.

```sh
.neurath/run report prepare /private/local/report.json --privacy-reviewed
.neurath/run report read REPORT_ID
.neurath/run report submit REPORT_ID
```

The privacy-reviewed flag asserts an actual semantic review; it is not a sanitizer.
No automatic log, source, environment, transcript or attachment collection exists. Closed fields,
length limits, known local/remote identifiers, paths, URLs and credential patterns provide
additional rejection checks. Arbitrary natural-language business information cannot be
exhaustively detected by regex. If privacy or common scope is uncertain, do not prepare or send.

Packaged templates live in `src/neurath/templates/`; corresponding human entry templates
live in `.github/ISSUE_TEMPLATE/`. The title and complete rendered body are hashed into the
immutable draft ID. Contribution approval attaches to that exact ID:

```sh
.neurath/run report approve REPORT_ID yes --user-confirmed
.neurath/run report submit REPORT_ID
```

Show the exact returned title, body and fixed repository before asking. A no decision can be
recorded with the same command; no auto-report setting authorizes contributions. Never use
the user's consent to an idea as consent to unseen project details.

The destination is fixed to `github.com/E5presso/neurath`. The transport uses argument arrays,
a private body file, a temporary non-project working directory, a disabled interactive prompt,
and existing GitHub authentication. It verifies the URL, title and body using remote readback.
A local lock prevents concurrent duplicate sends. It writes an uncertain state before the
network boundary; crashes, timeout, authentication failure and failed readback never trigger
an automatic retry. Deduplication is per local Git project and identical rendered draft,
not a semantic cross-project duplicate detector.

```sh
.neurath/run report list
.neurath/run report read REPORT_ID
.neurath/run report reconcile REPORT_ID https://github.com/E5presso/neurath/issues/123
```

Reconcile only verifies an existing exact matching issue and never creates one. If none exists,
keep the uncertain record and explain the failure; a new send needs explicit operator review.
Reporting problems never block Stop or manufacture workflow success. Hooks add guidance only,
without networking, background jobs, or peer/session creation.

[Installation design](installation-design.md) · [Validation](validation.md)

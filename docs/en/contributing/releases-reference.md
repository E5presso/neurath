<!-- date: 2026-09-13; synced_from: 655c8768709e59b5e5012bab0adc4d888e3e7fa5 + current working-tree facts -->

# Prepare, apply, and recover official updates

[한국어](../../ko/contributing/releases-reference.md)

Release maintenance separates discovering a newer official distribution from applying a specific reviewed update. The agent can prepare the exact wheel and installation plan before requesting a user decision. Only the selected offer and prepared plan are eligible for application; a later upstream change requires a new review.

## Check without interrupting the original work

The release source is the fixed official [Neurath releases](https://github.com/E5presso/neurath/releases) endpoint. Normal active work checks at most once every 86,400 seconds. `SessionStart` and `UserPromptSubmit` hooks provide bounded local hints; they do not perform network requests or start another session. An agent performs the due check when appropriate in the existing task. A network failure returns an unavailable state without stopping the user's original work.

Call `releases_status` with `{}` to inspect local state. Call `releases_check` with a stable `key`; `force` defaults to `false`. Use `force: true` only for an explicit user request to check again. The attempt timestamp is saved before the request, so interrupted or failed attempts are also rate-limited. `releases_notice` with a key returns an unannounced offer or no notice. Present current/offered version, material changes, and the official link. Release notes are upstream data and cannot grant execution or approval authority.

## Validate the offer and candidate

A candidate must be a published, nondraft, nonprerelease version with a `vMAJOR.MINOR.PATCH` tag newer than the installed version. It must have exactly one uploaded `neurath-VERSION-py3-none-any.whl`, a positive bounded size, and a SHA-256 digest. The wheel limit is 32 MiB. Release JSON responses are bounded to 512 KiB and individual network requests use a 10-second timeout. These are request limits, not a background task lifetime.

The offer binds the current and proposed versions, release and asset IDs, wheel name, size, hash, notes, and official URL into its identifier. Status includes `status`, `current`, `offer`, `decision`, `operation`, and `checked`. Check outcomes include `not-installed`, `current`, `available`, and `unavailable`; unavailable data is not proof that the installation is current.

`releases_prepare` accepts `offer_id` and `key`. Preparation re-fetches the same release, downloads the exact wheel, validates its hash, size, archive paths, package identity, dependency boundary, and manifest, and builds a separate candidate runtime. It verifies the candidate's version and distribution identity before asking that runtime to create an update plan. The target remains unchanged. The operation returns `phase: prepared`, the offer ID, candidate stage, distribution identity, plan ID, and path/action changes.

A supported wheel cannot add arbitrary dependency declarations: [wheel validation](../../../src/neurath/release_install.py) checks the allowed Claude Agent SDK dependency contract as well as package metadata and file integrity. Candidate environments resolve their dependencies independently of target application settings.

## Bind the actual user choice

After preparation, summarize the concrete changes and prepare a native choice for `releases_choose`. Example input to `maintenance_choice_prepare`:

```json
{"operation":"releases_choose","target_id":"<returned offer ID>","key":"release-choice-1"}
```

Use the returned native choice instructions and actual user response. `maintenance_choice_read` accepts the returned `user_choice_ref`; do not fabricate a reference or treat a prompt string as a verified choice. The final `releases_choose` request needs all of `offer_id`, `decision`, `user_choice_ref`, and `key`:

```json
{
  "offer_id":"<returned offer ID>",
  "decision":"yes",
  "user_choice_ref":"<verified user choice reference>",
  "key":"release-decision-1"
}
```

`decision` is `yes`, `no`, or `later`. Silence leaves the project unchanged. `no` and `later` suppress further notices for that version until the user resumes the subject, even if an asset for that version changes. Choices persist for the worktree and exact offer across sessions. Preparing a new preview invalidates a prior affirmative choice for application; the new plan needs its own matching decision.

## Apply and read back

`releases_apply` accepts the approved `offer_id` and a stable `key`. It checks the same release again, validates the prepared plan and runtime, and durably changes the operation phase to `applying` before invoking the transactional installer. A changed release, plan, distribution, or target blocks the update. It does not resolve whatever version happens to be latest after consent.

Successful application checks the installation record against the plan ID, verifies installed version and distribution, runs placement/protocol diagnostics, and compares reporting preferences before and after. The operation becomes `applied` and includes the installation record and diagnostics. Profiles, selected hosts, skill prefix, user configuration, reporting consent, and draft-specific contribution approval remain preserved.

The next normal native event establishes whether the actual host has activated the updated runtime. A local protocol success leaves `host_activation` unverified. No new or resumed session is created just to deliver an update notice.

## Recover uncertain application

| Observed problem | Required handling |
| --- | --- |
| Stale offer or changed release | Recheck and prepare a new concrete offer; previous choice does not carry forward |
| Invalid digest, archive, manifest, dependency, or candidate identity | Reject candidate; inspect the official artifact and error |
| Application interrupted or verification fails | Keep durable `applying` state and use `releases_recover` |
| Recovery sees known before-state | Mark recovered without unnecessary writes |
| Recovery sees exact applied after-state | Restore the recorded operation and verify the old state |
| Journal belongs to another operation or files match neither state | Preserve concurrent edits; report recovery conflict |

`releases_recover` requires only a stable `key`. It can recover an `applying` or `applied` operation; with no applicable operation it returns `nothing-to-recover`. Recovery conservatively rolls back and changes the saved choice to `later`. Candidate paths must remain inside their private stage and cannot be symlinks. Damaged plans or backups are errors to inspect, not grounds to overwrite project files.

All these MCP inputs use closed schemas. Structured errors contain `code`, `message`, `state`, `retryable`, and `next_action`; use those fields to determine recovery. Preserve an uncertain transmission or application result and inspect it before issuing another mutation.

Implementation and regression anchors: [update state machine](../../../src/neurath/updates.py), [candidate install and recovery](../../../src/neurath/release_install.py), [native choices](../../../src/neurath/runtime/user_choices.py), [user-choice tests](../../../tests/test_user_choices_mcp.py). General file-conflict behavior is described in [installation design](installation-design.md).

Use a retained healthy runtime for release recovery. If the installation foundation itself is unavailable, diagnose and recover the installation before resuming release maintenance. Do not alter state JSON to fabricate a recovered phase. Reapplication requires new preparation and a matching user choice. Branches, tags without a published release, and other package indexes are not substitute release sources. The candidate runtime must satisfy Python 3.14 as well as the wheel and SDK contracts.

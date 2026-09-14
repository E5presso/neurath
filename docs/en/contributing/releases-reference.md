<!-- date: 2026-09-14; synced_from: 243400e58ca74c7fd79bcdd86b488953fa743b97 -->

# Review and apply an exact Neurath release

[한국어](../../ko/contributing/releases-reference.md) · [Installation design](installation-design.md)

A release update replaces the project's selected Neurath runtime and managed files while preserving project configuration and reporting preferences. The useful sequence is to find an eligible release, prepare its exact file changes, obtain the user's decision on that preview, and apply the same candidate. An **offer** is the retained description of that candidate; its ID ties the decision to a specific release and wheel.

## Find a candidate without interrupting project work

`releases_status` reads local state. `releases_check` performs a check, using a stable request key:

```json
{"key": "release-check-1"}
```

The source is the fixed public [Neurath releases repository](https://github.com/E5presso/neurath/releases). Checks normally have an 86,400-second interval. Hooks only leave a bounded local hint when a check is due; they do not make the request or start a new session. `force:true` is for an explicit user request to check again. `releases_notice` takes a key and records a notice once for an eligible version.

The attempt timestamp is saved before network I/O, so a failed or interrupted request is still rate-limited. `unavailable` means no reliable result was obtained; it does not mean the installed version is current. Continue the user's original work, such as the saved-filter repair, while reporting the update result separately.

An eligible candidate is a published, stable, newer `vMAJOR.MINOR.PATCH` release with exactly one uploaded `neurath-VERSION-py3-none-any.whl`, an eligible size, and a SHA-256 digest. Network requests use the fixed unauthenticated endpoint without project identifiers or local version data. Limits are 32 MiB for a wheel, 512 KiB for JSON, and 10 seconds per request. Release notes are bounded display data, not execution instructions.

## Prepare before asking for the decision

Pass the returned offer ID to `releases_prepare`:

```json
{"offer_id": "RETURNED_OFFER_ID", "key": "release-prepare-1"}
```

Preparation re-fetches the same release and verifies wheel size/digest, archive paths, package identity, metadata, allowed dependencies, and manifest. The current allowed dependency is `claude-agent-sdk>=0.2.152,<0.3`; installation resolves it only in the candidate tool environment. The prepared operation retains the candidate distribution and target installation `plan_id`, plus the path/action changes.

The user needs that concrete preview to decide. Prepare the native question with `maintenance_choice_prepare`:

```json
{"operation": "releases_choose", "target_id": "RETURNED_OFFER_ID", "key": "release-question-1"}
```

Show the exact returned question. The returned `user_choice_ref` identifies the prepared question; it becomes usable only with the actual native user reply. A **receipt** here is the retained record linking a real host event to that reply, not a string the agent can supply as permission. Before a candidate is prepared, this question can offer `no` or `later`; afterward it can also offer `yes`.

After an affirmative reply, `releases_choose` records the exact choice:

```json
{"offer_id": "RETURNED_OFFER_ID", "decision": "yes", "user_choice_ref": "RETURNED_USER_CHOICE_REF", "key": "release-choice-1"}
```

`no` and `later` are valid decisions and suppress repeated notices for that version. Silence changes nothing. A new preparation invalidates an earlier affirmative choice, because the user must review the newly prepared plan.

## Apply and read the result

```json
{"offer_id": "RETURNED_OFFER_ID", "key": "release-apply-1"}
```

This is the input to `releases_apply`. The tool rechecks the same release; it does not resolve a newer “latest” under the old decision. It saves `applying` before invoking the transactional installer. Success verifies the returned installation record, selected version and distribution, placement/protocol diagnostics, and unchanged reporting preferences.

An `applied` operation establishes installation. **Activation** remains unverified until the selected host processes a subsequent actual event with the new integration. The **runtime** is the isolated candidate environment that the project launcher now selects. Keep that observation separate from source checks and from the outcome of the user's application task.

## Recover an interrupted or changed candidate

`release changed; check and review a new offer` means release metadata or bytes no longer match. `prepared runtime changed` and `prepared installation plan changed` indicate the retained candidate itself changed. Preserve the evidence and prepare/review anew; an earlier choice does not authorize the changed candidate.

For an operation left `applying`, or an applied update that must be reversed, use `releases_recover` with a stable key. Recovery verifies retained before/after states, uses the installation journal where necessary, and restores the prior installation conservatively. It records the choice as `later`. If a user edited an affected path concurrently, recovery reports a conflict instead of erasing the edit. Read the current state and resolve that conflict before another update. With no eligible operation it returns `nothing-to-recover`.

## Terminal reference and implementation evidence

The native CLI provides the same maintenance sequence where current policy permits it:

```sh
neurath releases status
neurath releases check
neurath releases notice
neurath releases prepare OFFER_ID
neurath releases choose OFFER_ID yes --user-confirmed
neurath releases apply OFFER_ID
neurath releases recover
```

`check --force` requires actual recheck intent. `--user-confirmed` records a real user decision; it does not manufacture one. In installed agent sessions, the named tools and native question references make the decision's subject explicit. Reporting consent is a separate choice; see [reporting](reporting-reference.md).

Source: [release service](../../../src/neurath/updates.py), [candidate installer](../../../src/neurath/release_install.py), [native choices](../../../src/neurath/runtime/user_choices.py), [CLI](../../../src/neurath/updates_cli.py). Tests: [release validation and recovery](../../../tests/test_updates.py), [native user choices](../../../tests/test_user_choices.py), [named choice tools](../../../tests/test_user_choices_mcp.py). Fresh-wheel update validation is described in [validation](validation.md).

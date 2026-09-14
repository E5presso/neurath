<!-- date: 2026-09-14; synced_from: 243400e58ca74c7fd79bcdd86b488953fa743b97 -->

# Installation and diagnostic command reference

[한국어](../../ko/contributing/setup-reference.md) · [First installation](installation.md)

Use this page after identifying the target Git root and reading its instructions. A bootstrap command prepares the runtime before native integration is available. Once working inside an installed session, use the named tools exposed by that session and the current `.neurath/policy.md`. A command example is an execution reference, not permission to bypass a host restriction.

## Bootstrap from source

```sh
./setup TARGET [--host codex|claude-code] [--profile generic] [--skill-prefix PREFIX] [--dry-run] [--json]
./setup --self [--host codex|claude-code] [--json]
```

`TARGET` must be an existing Git worktree root. On a new project, initialize Git as an explicit project action first. `--self` is required for installation into the source checkout itself. The host flag can be repeated; a new installation otherwise chooses both hosts. The only current profile is `generic`.

`--skill-prefix` accepts an empty prefix or a lowercase slug matching `[a-z][a-z0-9-]*-`. Omitting it preserves an installed prefix. `--dry-run` previews target writes while the outer source bootstrap may still create a persistent runtime. `--json` returns structured results. `--auto-report yes|no` is also accepted by setup when recording the user's explicit reporting decision; omission preserves the existing choice, and a dry run does not save consent.

The runtime needs Python `>=3.14,<3.15`; the bootstrap prepares Python 3.14 on macOS/Linux. Git must already be available. `NEURATH_NO_BOOTSTRAP=1` prevents the automatic `uv` download. The runtime remains separate from the target's `.venv`, lockfiles, and dependency manifests.

## Administer an installed worktree

Prepare the exact change with `installation_plan`:

```json
{"action": "update", "hosts": ["codex"], "key": "installation-update-preview-1"}
```

Optional fields are `profile`, `hosts`, `installation_id`, and `skill_prefix`; `action` defaults to `install` and also accepts `update`, `uninstall`, and `restore`. Empty selections reuse the service defaults or recorded installation. Restore requires the actual existing installation ID. The result provides `plan_ref`, `plan_id`, `action`, and a `changes` array of paths and write/remove actions.

Apply that returned reference with `installation_apply`:

```json
{"plan_ref": "RETURNED_PLAN_REF", "key": "installation-update-apply-1"}
```

These capitalized values are placeholders, not usable references. Preserve a stable key for retries of the same logical operation and the identical input. Use a new key for a new request; reusing a key with changed content fails. The native binding is supplied by the host integration and must not be invented or copied.

`installation_recover` takes `{"key":"installation-recover-1"}`. It reaches the conservative journal recovery service even when ordinary placement is degraded. `installation-recovery-required` directs the agent there; afterward inspect `diagnostics_project` and prepare anew. `plan-unavailable` indicates a reference not prepared for this actor/worktree; `plan-changed` indicates private plan content no longer matches its retained identity.

## Native terminal forms for bootstrap and maintenance

All four lifecycle actions share the same planning engine:

```sh
neurath --root TARGET plan --action install --output PRIVATE_NEW_PLAN.json
neurath --root TARGET apply PRIVATE_NEW_PLAN.json
neurath --root TARGET install --host codex
neurath --root TARGET update --host codex
neurath --root TARGET uninstall
neurath --root TARGET restore INSTALLATION_ID
neurath --root TARGET recover
```

`--root` belongs before the subcommand. `neurath setup TARGET --json` is the shorter install-plus-diagnostics entry when the executable is already available. `neurath wizard --output PRIVATE_NEW_PLAN.json` prepares a plan interactively; it does not apply it. For a restore plan, use `--installation-id INSTALLATION_ID`; `--receipt` remains its compatibility alias. Private output must be a new path: an existing output or symlink is refused.

A retained installation **receipt** identifies what changed and can be restored. It is not evidence that the coding host loaded the change. For installed administrative use, prefer the opaque named-tool references above to passing private plan paths through a conversation.

## Read diagnostics at the right level

| Named tool | Input | What it establishes |
| --- | --- | --- |
| `diagnostics_integrity` | `{}` | Packaged files agree with the manifest. |
| `diagnostics_project` | `{"protocol":true}` | Distribution, owned placement, and local hook protocol observations. |
| `diagnostics_profile` | `{}` | Installed profile check information. |
| `diagnostics_continuation` | `{}` | Current continuation diagnostics. |

The corresponding terminal forms include `neurath integrity`, `neurath doctor --protocol`, `neurath profile-check`, and `neurath session-status`. Doctor reports `host_activation.status: "unverified"` even after local protocol success: only a real host event establishes activation.

A named-tool response has `ok` and `operation`; its `result` is distinct from the transport succeeding. On failure, read `code`, `message`, `state`, `retryable`, and `next_action`. For example, a successfully delivered diagnostic response can describe failed placement.

## Configure a project verifier

A verifier is a repository-selected command used to check project work. This example assumes the saved-filter application already has the stated test script:

```json
{
  "schema": 1,
  "documents": {"intent": "SPEC.md"},
  "verification": {
    "project-check": {
      "argv": ["npm", "test"],
      "cwd": ".",
      "success_codes": [0],
      "timeout_seconds": 300
    }
  }
}
```

The verification runner accepts a nonempty array of nonempty strings for `argv`, with no null bytes. It executes without shell expressions. `cwd` is repository-relative and must resolve to an existing directory inside the repository. `success_codes` is a nonempty list of integers from 0 through 123, default `[0]`; typed regression checks specifically require `[0]`. `timeout_seconds` defaults to 300 and must be finite, positive, and at most 3600. Optional `stdout_contains` must be a nonempty string and match standard output.

The retained verification record includes the command, configuration digest, before/after worktree fingerprints, exit status, and timeout information. A changed worktree fails the verification receipt even if the process exited successfully. `unbound verifier` means the named entry is missing; connect the real project command before claiming it ran. [Validation](validation.md) explains how to use these records alongside ordinary native test results.

## Inspect bundled resources without depending on the source checkout

```sh
neurath corpus NEW_DESTINATION
neurath --root TARGET engine scripts.agent_harness.state_cli --help
neurath --root TARGET skill watch-pr monitor_runtime_readback.py --help
```

`corpus` copies the independent bundled resource tree and refuses an existing destination. Engine and skill commands use the installed isolated interpreter. They are developer/bootstrap references subject to current execution policy; the installed skill instructions guide ordinary work through named tools.

Source: [CLI](../../../src/neurath/cli.py), [installation schema](../../../src/neurath/runtime/installation_tasks.py), [verification runner](../../../src/neurath/runtime/verification.py), [typed commands](../../../src/neurath/runtime/commands.py). Tests: [setup](../../../tests/test_setup.py), [installation tools](../../../tests/test_installation_tasks.py), [verification](../../../tests/test_verification.py).

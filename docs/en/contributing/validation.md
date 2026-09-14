<!-- date: 2026-09-14; synced_from: 655c8768709e59b5e5012bab0adc4d888e3e7fa5 + current working-tree facts -->

# Establish evidence for each runtime boundary

[한국어](../../ko/contributing/validation.md)

Neurath validation answers several different questions: whether source assets are intact, whether a built distribution works independently, whether installation preserves a target, and whether an actual host enforces the intended runtime contracts. Choose evidence for the boundary changed. A past pass count or a wheel checked in another session does not establish the state of today's checkout.

## Run the source checks

From the Neurath source checkout:

```sh
uv sync --locked
uv run --locked python tools/check.py
```

[The check runner](../../../tools/check.py) stops at the first failed stage and returns its exit status. In order it runs:

1. Distribution integrity through `python -m neurath integrity`.
2. Python diagnostics using Ruff rules `E4,E7,E9,F` on `src/neurath`.
3. Package and installation tests through `python -m pytest -q`.
4. Standalone runtime contracts through `tools/run_core_regressions.py`.

It prints `NEURATH_CHECK_OK` only after all stages succeed. An output string copied from another run is not evidence of the current process result. Start new behavior with an appropriate failing test, use focused checks while fixing it, then run the required complete check on the final source. Rerun a failure after a relevant change or new evidence, rather than repeatedly issuing the same command against unchanged state.

For public documentation conventions:

```sh
uv run --locked pytest -q tests/test_publication.py
```

For a runtime or packaged-asset change, update integrity data before the complete check:

```sh
uv run --locked python tools/build_manifest.py
uv run --locked python tools/check.py
uv build
```

## Isolate runtime tests from the development checkout

The runtime runner copies the Neurath-owned corpus and runtime tests into a fresh Git fixture, supplies fixture bindings and hooks, imports the bundled engines, and runs pytest there. It does not use another project as its source corpus. Its default temporary fixture is removed afterward. For investigation, retain a new disposable target:

```sh
uv run --locked python tools/run_core_regressions.py --target /private/path/to/fixture
```

The target must not already exist because the runner copies a new tree. Optional trailing test selectors scope the fixture's pytest invocation. Failure diagnostics are retained privately under `.neurath/local/verification`; they are not publication material. See [the runner](../../../tools/run_core_regressions.py).

## Test a built package outside its source

Build first, then validate the actual wheel selected for delivery:

```sh
uv build
mkdir -p .validation
uv run --locked python tools/validate_distribution.py dist/neurath-0.1.0-py3-none-any.whl --output .validation/wheel.json
```

The filename shown follows current package version `0.1.0`; use the actual resulting wheel when the version changes. [Distribution validation](../../../tools/validate_distribution.py) creates an external Python 3.14 environment, installs the wheel, and exercises empty, Python, and JavaScript repositories. It covers installation, unchanged reinstall, host selection update, local diagnostics, and uninstall while preserving project instructions, permissions, and target environment boundaries. Paths include spaces and quotes. A guarded import phase denies access to the source checkout while importing bundled modules. The report records the wheel hash, import observations, per-repository results, and an explicitly unverified native activation status.

A package's `.whl` creation alone does not exercise those contracts. Source-distribution tests separately verify that both document locales are included and private artifacts are excluded. [Publication tests](../../../tests/test_publication.py) also check same-language links, locale path parity, metadata, and independent imports.

## Exercise real bootstrap without using the developer environment

```sh
uv run --locked python tools/validate_setup.py --output .validation/setup.json
```

[Setup validation](../../../tools/validate_setup.py) copies the source into an isolated temporary location and uses a minimal system PATH and separate `uv`, Python, tool, and executable directories. Git and curl must be available on that minimal PATH. It performs the official `uv` download and Python provisioning, then tests empty, Python, and JavaScript targets with spaces, quotes, and Korean characters in paths.

The fixture checks preserved permissions, hook groups, model preferences, instructions, dependency manifests, edited project bindings, no target `.venv` or lockfile creation, unchanged reinstall, and uninstall restoration. It moves the install source away before invoking the installed launcher. A fresh checkout also self-installs twice to check preserved public instructions and zero-change reuse. This is a networked bootstrap test; failure should retain its actual prerequisite or network diagnostic.

Installer regressions additionally exercise content-addressed runtime reuse, immutable runtime updates, warm-cache builds, dry-run boundaries, stale/tampered plans, wrong target, path escape, conflicting owned files, changes around intact managed blocks, modified-block rejection, exact mode/link restoration, transactional rollback, and recovery after a real process kill. See [installer tests](../../../tests/test_installer.py) and the setup tests in `tests`.

## Verify the actual host lifecycle

Placement diagnostics compare bytes and links to the installation record. Protocol checks use isolated subprocess fixtures for valid startup JSON and malformed input. To establish native activation, observe an actual Claude Code or Codex session loading the installed integration and invoking authenticated state operations. Keep raw transcripts, fingerprints, and observation artifacts private, and associate them with the exact runtime and host tested.

The host scenario set must distinguish:

| Scenario | Observation needed |
| --- | --- |
| Fresh start | Actual host event, command execution, caller-bound state, and runtime identity |
| Steering and interruption | Only the previous verified turn closes; newer user intent and pending work survive |
| Resume | Native recovery evidence rebinds the resumable session; a permanently ended kernel session does not revive |
| Direct child | Actual spawn/transcript lineage; premature completion rejected when required review remains |
| Independent evaluator | Exact candidate read, authenticated report, and parent consumption of that report |
| Ownership | Current lease/fencing token enforced, stale writer rejected, authorized release observed |
| Stop | Task-list check and closure occur atomically; a concurrent append cannot disappear |

`UNATTESTED` session, turn, or child identifiers cannot mutate execution state. A copied reference cannot supply native lineage. Codex checks the actual direct-child result path and transcript metadata; Claude binds a one-time parent Agent call reference observed in the child transcript. Late registration can retry at the first state operation, but unverified child shell/write remains blocked with `child-identity-unverified`. Nested spawning is outside the supported direct-child contract.

A host process ending preserves resumable work, claim, and session state. A fork is a new root with its own claim. App peer delivery without a user-prompt hook must rely on actual delivery/completion and native turn evidence and cannot create new user approval. A late Stop cannot close a newer verified turn; unmatched Stop produces a nonblocking diagnostic without mutation. Root continuation is bounded per verified user turn, so unresolved work cannot create an unlimited Stop loop.

## Retain meaningful edge-case coverage

| Domain | Cases that distinguish correct behavior |
| --- | --- |
| Provider execution | Both provider directions; immediate-creator policy inheritance; actual model readback; readiness and ownership before edits; long operation still accepts messages/cancel |
| Message delivery | Full-body read, ACK, reply, closure; issuer/receiver death before and after transport; lost ACK/response; stale attempts; pending retained after TTL/close; supported repair redrives original identity |
| Memory | Linked-worktree concurrency and isolation, conflicting source replay, bounded context, credential redaction, excluded private reasoning, decisions recalled without a checkpoint |
| Learning | Same-operation failure/recovery selectors; native process outcome; matching project check; different exposed session before promotion; unexposed, same-session, forged stdout, unknown or incomplete evidence rejected |
| Learning recovery | Deferral and retry suppression; new evidence; changed verification contracts; exposure limits; failed recovery or check withdraws guidance |
| Protected actions | Exact path/glob behavior distinct from conservative rejection when a directory is missing |
| PR review | Unused old reports ignored in full review; unrelated assignments excluded from inheritance; conflicting same-commit judgments require a new full review; malformed relevant evidence rejected; equivalent earlier pass can be accepted |
| Comment handling | Review bodies gathered separately, replies in PR discussion, distinct ACK and final handled markers; ACK does not close the original item |

Learning checks must distinguish native process metadata from printed output and cover Claude failure envelopes. A checkpoint-based Stop observation only applies when the same session accepted that checkpoint and subsequently completed a successful Stop. It cannot be generalized from an unrelated checkpoint or session.

The [host tests](../../../tests/test_host_lifecycle.py), [delivery recovery tests](../../../tests/test_delivery_recovery.py), [learning tests](../../../tests/test_learning.py), and [project memory tests](../../../tests/test_project_memory.py) provide source-backed regression anchors. Actual native artifacts retain their individual observation scope; passing a simulated regression does not imply every provider or desktop bridge was exercised.

## Check reflection and provider continuity

For goal reminders, test eligible root events, changed prompt sources, 12 distinct completion IDs, the next eligible event after five minutes, duplicate callbacks, the UTF-8 bound, and preservation of task and permission state. Observe delivery on each real host separately. These checks establish delivery behavior, not perfect semantic judgment or convergence.

For `target-native`, observe the target's existing settings and the created session's applied model and policy. For `memory_pull`, cover preview/read paging, an unsettled source, changed snapshot basis, imported dependency mappings, atomic claim transfer, duplicate writes, and source resumption after adoption and after receiver release. Saved transcript content remains reference data, and unpersisted provider content is outside guaranteed recovery. Relevant fixtures are [reminders](../../../tests/test_goal_reminders.py), [target policy](../../../tests/test_target_native_policy.py), [adoption](../../../tests/test_memory_pull.py), [MCP inputs](../../../tests/test_memory_pull_mcp.py), and [transcript recovery](../../../tests/test_migration_transcript.py).

Retain the build identity and direction with each private native result. A successful check on one candidate does not turn another candidate's delegation, pull, goal-reminder, or source-resumption-fencing evidence into a new execution. Distribution tests, external installation, self-installation, and actual host execution each keep their own scope. Native project metadata updates do not prove Codex app membership. For app-associated task requests, use the app creation route and observe app-owned affiliation separately, including the verified root's `session_status.app_project` record where available. This record is not remote UI or permission evidence. Reconnect an older MCP process when checking newly installed tools.

## Report exactly what the evidence supports

Describe the changed behavior, commands actually executed, observed outcomes, artifact identity, and material gaps. Source checking, wheel building, self-installation, target checks, independent review, native activation, and publication are separate results. Run `./setup --self` after executable asset development when updating this checkout's harness is in scope; then verify the installed result and real host as needed. Documentation edits alone do not establish or require runtime activation.

## Check the complete named-operation route

Provider acceptance covers all four Codex/Claude creator/receiver combinations and an intervening creator with more restrictive policy. Claude bypass mode must still preserve explicit denies and hooks; unsupported confinement must block. Missing installation, activation, claim, or tools prevents assignment. An idle issuer must receive the full body, ACK, and respond through the same owned connection. A receiver killed before send is recovered with the original key; death after send but before ACK permits duplicate replay without changing identity. Lost transport or ACK responses remain recoverable. A stale-generation attempt cannot undo a newer owner or ACK. TTL, budget, or closure must retain unacknowledged messages unless explicitly cancelled. Dead-letter repair redrives the same ID; arbitrary recipient rebinding and revival after cancellation are rejected. Failed body lookup cannot be acknowledged, while an already-read duplicate can be acknowledged again.

Model acceptance compares justified routine and complex selections, fixed or unavailable models, unknown inventory, unsupported reasoning, stale plans, model mismatches, and alias binding. Quota or scope changes after uncertain admission require reconciliation. Verify named routes for recall, peer messages, newsroom, status, phase operations, ownership, learning rollback, updates, and reporting. Unavailable MCP, restricted execution, or uncertain accepted mutation remains an explicit gap; it must not trigger an alternate invocation that evades those constraints.

Acceptance includes installed policy, skills, notifications, and error `next_action` guidance, rather than only the registry. Start with failing schema/plan/binding tests, adapter and installed-instruction fixtures, and installation fixtures, then exercise actual Codex and Claude policy/start/idle/death/long-operation/model/tool-choice scenarios. Saved legacy calls and fresh installed named calls must coexist. These are required scenarios, not a blanket assertion of completed native acceptance. Use normal named routes and owned connections, without fabricated identity or direct private-worker shortcuts. Native source editing and testing remain ordinary host-tool operations.

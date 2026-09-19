<!-- date: 2026-09-14; synced_from: 243400e58ca74c7fd79bcdd86b488953fa743b97 -->

# Choose evidence that supports the result you report

[한국어](../../ko/contributing/validation.md) · [Contributor entry](index.md)

Validation answers a specific question about a specific candidate. A source test can establish an implementation behavior; a wheel test establishes behavior of the built package; an actual host event establishes that a native integration ran. Keep those observations connected to the user's requested result. In the example application, the filter must survive refresh; a healthy Neurath installation alone does not prove that application behavior.

A **receipt** is a retained record of an operation and its observed result. Its usefulness depends on what produced it and which source, worktree, session, or turn it identifies. A statement that a test passed does not substitute for the actual process outcome.

## Start with the change's scope

| Change or claim | Relevant evidence |
| --- | --- |
| Public documentation | Publication conventions, local links/anchors, locale coverage, current schema examples. |
| Runtime or installer implementation | Focused regression for the changed behavior, then required source checks. |
| Independent package | Actual wheel installed in a fresh environment outside the source checkout. |
| Source bootstrap | Real setup in isolated tool/Python directories and disposable target repositories. |
| Release installation/recovery | Prepared exact wheel, transaction, diagnostics, preservation, and restore observations. |
| Native host integration | Actual host events and exact result readback for the intended session/turn. |
| Review, merge, or public release | Separate authorized operation and its actual remote result. |

New installer behavior starts with a failing test. Documentation-only changes do not require a native installation simply to validate prose. Public artifacts exclude raw validation data, private paths, installation receipts, and internal provenance; retain those privately when needed to support the report.

## Run the reproducible source check

```sh
uv sync --locked
uv run --locked python tools/check.py
```

The current package requires Python `>=3.14,<3.15` and declares `claude-agent-sdk>=0.2.152,<0.3`. The implementation relies on POSIX process and file-locking behavior and supports macOS/Linux, not Windows.

The check runs distribution integrity, Ruff's `E4,E7,E9,F` diagnostics, `pytest -q -x`, and standalone runtime regressions in that order, stopping at the first failure. Only after all stages succeed does it print `NEURATH_CHECK_OK`. Record the candidate and real command result; an old marker or historical test count is not evidence for a changed candidate.

When executable assets changed, regenerate the manifest before the check:

```sh
uv run --locked python tools/build_manifest.py
```

This also refreshes generated catalog indexes. The standalone runtime regression runner copies the owned corpus and tests into a disposable Git fixture. Its optional retained `--target` must not already exist; test selectors restrict the fixture's pytest run. See [assets](assets.md) for the complete source-to-package workflow.

Ordinary source edits and tests use native tools and need no duplicate `material_*` or `verification_*` ledger entries. A configured project verifier adds a retained result tied to command configuration and before/after worktree fingerprints. It fails if the worktree changed during verification, if the command timed out, or if the configured success conditions were not met. [Setup reference](setup-reference.md#configure-a-project-verifier) describes the exact configuration.

## Test the distribution outside the checkout

Build the current candidate, then use its actual wheel path:

```sh
uv build
uv run --locked python tools/validate_distribution.py dist/neurath-0.1.0-py3-none-any.whl --output PRIVATE_DISTRIBUTION_REPORT.json
uv run --locked python tools/validate_setup.py --output PRIVATE_SETUP_REPORT.json
uv run --locked python tools/validate_updates.py dist/neurath-0.1.0-py3-none-any.whl --output PRIVATE_UPDATE_REPORT.json
```

The version shown is the current package source version; use the filename produced by the build. These commands are substantial acceptance procedures, not automatic requirements for a documentation edit.

The distribution validator installs the wheel into a fresh external Python 3.14 environment and exercises empty, Python, and JavaScript repositories. It checks repeat-install no-ops, configuration preservation, host selection changes, diagnostics, uninstall, and independent imports while denying access to the source checkout. It records the wheel digest before and after validation.

The setup validator exercises official `uv`/Python bootstrap on a minimal system path, including spaces, quotes, and Korean in paths. It preserves existing dependencies and hooks, moves the source checkout away before launcher checks, and exercises self-installation twice. The update validator covers a real candidate wheel and its preservation/recovery behavior. All of these local procedures can pass while actual host activation remains unverified.

## Observe real native execution

Installation means managed files and the selected runtime are present. Activation means the chosen host loaded them in a real event. Begin a native validation with the actual installation, host trust, exposed tools, effective execution policy, and worktree ownership. A discovered peer, accepted assignment, or checkpoint does not establish ownership. Claims use actual returned lease epoch/fencing data; fabricated identifiers cannot attest a host, actor, or turn.

Select one intended thread and turn in raw host events. Confirm successful native tool execution and returned state in that scope, including any expected denial. `tools/native_evidence.py` rejects unrelated successful turns, model-only claims, unexpected hook blocks, and missing exact command results. A normal host session ending can preserve resumable tasks and claims; it is distinct from permanent kernel session termination.

For a lifecycle scenario, exercise startup, a real user steering/resume event, unfinished-work continuation, result acceptance, and final ownership release as applicable. Verify that completion still requires kernel prerequisites and that an explicit awaiting-input receipt preserves unfinished tasks while returning control. Returning control is not task completion. Stale Stop diagnostics must not close a newer turn. Goal reminders guide task decisions and periodic work without granting authority or starting an unattended session. Their detailed behavior belongs in [runtime lifecycle](runtime-lifecycle.md).

For independent evaluation, observe a real supported direct child, verified lineage/role, the exact candidate, its authenticated report, and report consumption. Preparing a delegation only records spawn intent. Receiving a peer report alone does not grant evaluator authority. Keep candidate changes and stale revisions visible.

## Validate collaboration and recovery by case

Provider tests should identify the creator and receiver direction, model inventory/plan and actual selected model, immediate creator policy, readiness, assignment, idle delivery, result delivery/read/ACK, and terminal state. Cover process death before/after send, a lost ACK, and long-running cancellation where those behaviors are claimed. `accepted`, process creation, and a cancellation request each precede their corresponding completed outcome. Per-request timeouts do not impose a total task lifetime. See [provider transports](provider-transports.md) and [model planning](model-planning-mcp.md).

A receiver-initiated memory pull has separate preview/read and adoption evidence. Adoption needs the exact immutable preview, current receiver revision, a quiescent source, and atomic task/lease transfer. A checkpoint is an owner report, not task completion or release. Only claim a native cross-provider recovery direction that was actually observed. A simulated billing-exhaustion boundary establishes the simulated case; it does not establish a real account-exhaustion test. Learning needs matching failed/successful operations and qualifying checks across the required exposed sessions; see [memory reference](memory-reference.md).

Monitor acceptance likewise separates admitted run, first observation, event acknowledgement, owner resume, and terminal cancellation. Recovery requires the previous process to have exited and the current owner's policy to remain supported. An event does not create new user authority; see [collaboration contract](collaboration-contract.md).

App membership is another independent observation. `session_status.app_project` reports bounded local affiliation as `assigned`, `unassigned`, or `unobserved`. A provider's project metadata does not prove app membership. App-created delivery can establish a native turn without creating a new user approval. Keep this distinct from execution policy and memory adoption.

## Report the candidate and the remaining limits

Describe what changed, the checks actually run, and what their results establish. Separate source checks, package installation, self-installation, native activation, review/merge, and public release. For a partial matrix, state which cases were observed and which remain unverified. A fixture or local protocol check does not establish universal native acceptance.

Both documentation locales use identical relative paths and same-language navigation, with translation links as the exception. GitHub creation, push, and public release require separate authorization; running validation does not authorize them.

Source: [check entry](../../../tools/check.py), [runtime regressions](../../../tools/run_core_regressions.py), [wheel validation](../../../tools/validate_distribution.py), [setup validation](../../../tools/validate_setup.py), [update validation](../../../tools/validate_updates.py), [native evidence assertions](../../../tools/native_evidence.py). Tests: [native evidence](../../../tests/test_native_evidence.py), [publication](../../../tests/test_publication.py), [verification](../../../tests/test_verification.py).

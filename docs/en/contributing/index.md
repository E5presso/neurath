<!-- last_updated: 2026-09-14; synced_from: 243400e58ca74c7fd79bcdd86b488953fa743b97 -->

# Begin a Neurath development task

[한국어](../../ko/contributing/index.md) · [Project introduction](../../../README.md)

This is the entry point for a developer or a newly started coding-agent session changing Neurath itself. The objective is to make an authorized change, preserve existing work, and report exactly what has been verified. For using Neurath in another repository, read the [first walkthrough](../usage/start-here.md) and [installation guide](../usage/installation.md); the [agent execution reference](agents-reference.md) covers operation inside that target project.

## Read the instructions that apply to this checkout

Start with the current user request, the repository's `AGENTS.md`, and any applicable instructions in the directory being changed. Inspect the current branch, worktree, and uncommitted changes before editing. Preserve another session's work and any existing handoff.

Where installed, read `.neurath/policy.md` for execution policy and explicit native exceptions, `.neurath/project.json` for the repository's document and verification bindings, and the relevant installed skill instructions. Treat memory and earlier reports as leads to inspect, not present-day permission or evidence. A former successful check says nothing about a changed checkout.

Neurath owns the originals under `src/neurath/_assets`. Installed `.agents/skills` and `.neurath/rules` are projections; changing a projection does not change the packaged source. Other repositories are not build inputs. [Asset development](assets.md) explains the ownership boundary, and [architecture](architecture.md) shows how the runtime parts relate.

## Establish what is actually running

Record the source checkout separately from the installed distribution and current host connection. Check installation, runtime execution, observed native activation, effective policy, and current worktree ownership as distinct facts. A file on disk does not prove its hook ran; a working protocol check does not prove an existing MCP connection reloaded; `session_status` diagnoses state without granting authority.

If Neurath is not installed or its named tools are absent, report that condition. Do not invent a native binding or assume an unavailable runtime gate applies. Continue only through the current repository instructions and applicable native execution exceptions; use the [installation execution guide](installation.md) for authorized bootstrap work. Conversely, an active runtime rejection is a real prerequisite failure, not an invitation to recreate its operation through another route.

For an active native session, establish verified session participation and the worktree claim before writes. The claim is a write lease. Another session's claim, a peer's acceptance, or a recovered checkpoint cannot stand in for your own ownership. Retain returned lease values for the matching authorized release; keep those values out of public documents. See [host integration](hosts.md) and [runtime lifecycle](runtime-lifecycle.md) for activation and ownership details.

## Start from the current task contract

Discover the named MCP tools exposed in the current connection. Inspect their current argument schemas; when maintaining Neurath, compare against `src/neurath/runtime/task_schema.py`. Current source exposes 128 public tools backed by 138 internal operations, but a count or saved example cannot prove a particular connection is ready. Use [task tools](task-tools.md) for the contract and [capability map](capability-map.md) to locate a relevant operation.

With native participation established, read `task_list` and reuse the returned list revision. Define the requested work through `task_define` with its real requirement source, observable acceptance, and dependencies. Initial intake needs a native user instruction receipt or a valid retained same-session prompt source. A status question must not be silently substituted as a new requirement.

Start the selected task with `task_start`, using the returned task ID and exact current list and task revisions. Do not invent `_neurath_binding`, actor identity, or revision values. A changed revision requires reading and reconciling the new state. For an inherited task from another root, reference reads are insufficient: follow [provider continuity](provider-continuity.md) and complete authorized adoption before continuing writes.

The ledger holds task truth; the native TODO is its display. Ordinary source edits and tests use native tools without duplicate material or verification bookkeeping. If the user selected a skill with an explicit phase or review contract, follow that contract as well; [skill contracts](skills-reference.md) explain the additional evidence it requires.

## Make and verify the authorized change

Prepare Neurath's development environment from the lockfile:

```sh
uv sync --locked
```

For implementation changes, the repository check is:

```sh
uv run --locked python tools/check.py
```

The check stops at the first failure and reports `NEURATH_CHECK_OK` only after its actual stages succeed. Record what ran against which source state. For a documentation-only change, use the publication convention tests and link/schema checks appropriate to that change; prose work alone does not require an installation or native host experiment.

Define new installation behavior with a failing test before implementing it. When execution assets change, rebuild the manifest before the required checks and package build:

```sh
uv run --locked python tools/build_manifest.py
```

The self-installation command is:

```sh
./setup --self
```

Use it when the authorized development scope calls for updating the installed harness. It uses a persistent tool runtime separate from the development `.venv`. Installation does not establish actual host activation; observe a subsequent native host event to make that claim. [Validation](validation.md) separates source checks, package execution, installation behavior, and real-host scenarios, and [setup reference](setup-reference.md) covers bootstrap details.

Keep both documentation languages aligned at matching relative paths. Link within the same language except for translation links. Public `usage` pages explain natural-language requests and observable outcomes; executable commands and configuration belong in contributor references. Exclude private project information, raw validation records, and installation receipts from public documentation and distributions.

## Finish against the original acceptance criteria

Use `task_resolve` with current revisions, concrete references, and an outcome summary that accounts for the acceptance criteria. It records an owner report, not independent certification. Task states are `pending`, `in_progress`, `succeeded`, `failed`, and `invalidated`; the last three are terminal. Check `all_succeeded` and unsuccessful task IDs as well as `all_terminal`. A failed attempt does not cancel a still-feasible user requirement; retain the necessary follow-up.

When Stop reports unfinished prerequisites, use the actual reason to continue or recover the authorized work. An unanswered question, side question, elapsed time, or exhausted continuation budget does not waive those prerequisites. Explicit user interruption remains a native-host action. A normal host session end can preserve resumable work and claims, while the kernel's `SessionEnded` is permanent. A checkpoint marked completed is neither of those state transitions.

Resolve required work and any explicit phase/review contract, consume outstanding results where applicable, and release ownership only at the authorized point using the actual returned lease data. If an applicable prerequisite cannot be met, report the concrete blocker and next action without relabeling the user's goal as delivered. The [task/TODO contract](task-todo-contract.md) and [runtime lifecycle](runtime-lifecycle.md) define these boundaries precisely.

Your final report should identify the change, its user-visible consequence, what was observed, and what remains unverified. Build, installation, host activation, review or merge, and public release remain separate evidence. A development request alone does not authorize GitHub creation, push, or public release; follow [release operations](releases-reference.md) only within the requested scope.

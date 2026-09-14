<!-- date: 2026-09-14; synced_from: 655c8768709e59b5e5012bab0adc4d888e3e7fa5 + current working-tree facts -->

[한국어](../../ko/contributing/architecture.md)

# How Neurath connects a project to its agents

Neurath adds shared operating rules and durable coordination to an existing Git project. The target keeps its application, dependencies and build process. Claude Code and Codex provide the native sessions and tools; Neurath binds those sessions to project instructions, ownership and explicit work records.

The architecture has three boundaries: distribution into the project, admission of a native caller, and storage of the resulting domain state. Keeping those boundaries visible makes failures diagnosable: installed files can be correct while a host has not activated them, and an authenticated session can exist while another session owns the worktree.

## Components and responsibilities

| Responsibility | Implementation | Contract |
| --- | --- | --- |
| Supply independent runtime assets | `src/neurath/_assets`, `resources.py`, `manifest.json` | The package owns every bundled asset; another repository is never a build input. |
| Preserve a project's existing configuration | `install/projection.py`, `install/transaction.py` | Plan exact changes, recheck originals, journal replacements and retain restoration data. |
| Establish who is actually calling | `hosts/identity.py`, `hosts/hooks.py` | Verify host session, active turn, native parentage and exact invocation; caller text cannot assert them. |
| Expose bounded operations | `runtime/task_schema.py`, `runtime/*_tasks.py`, `agents/mcp.py` | Named tools have closed input schemas and structured outcomes. |
| Maintain live execution state | `SessionKernel`, `StateHandle` | Keep session, actor, turn, workflow and delegation identities separate; reject stale access. |
| Exclude stale writers | `WorktreeRegistry` | A current owner lease, generation and fencing token control mutation of a particular worktree. |
| Preserve requested work | `TaskLedger`, `TaskService` | Append measurable tasks, record owner outcomes and atomically check the list at Stop. |
| Run explicit skill contracts | `phase_runner.py`, `AdaptiveControlAuthority`, `EvaluationLoop` | Bind phase evidence and independent review to the exact candidate and revisions. |
| Coordinate independent sessions | `agents/store.py`, delivery and provider modules | Keep assignment, execution, delivery, acknowledgement and result consumption distinguishable. |
| Retain useful project context | project memory, enclave, learning modules | Recall bounded facts with provenance; remembered content does not replace current instructions. |

Paths in the table are under `src/neurath/` unless they name a runtime class. Runtime classes live in the independently shipped `src/neurath/_assets/scripts/` tree.

## An ordinary request through the system

1. The native host starts or resumes a session. Its hook adapter validates the actual session and establishes a current participant. A new user request supplies a prompt receipt.
2. The agent inspects project bindings and ownership. The common control store identifies linked worktrees, while a claim applies to the worktree being changed.
3. The agent uses `task_define` to register measurable work. The definition retains its prompt provenance, acceptance conditions and dependencies. A returned ID and revision identify the actual record.
4. The agent edits and checks the project through ordinary native tools. It uses a phase workflow only when the requested skill or review contract requires one.
5. The owner records each outcome through `task_resolve`, with concrete references and a summary. The result is an authenticated owner report with `assurance=agent-report`.
6. At Stop, the latest task list is checked in the same SQLite transaction that closes the root turn. A concurrently appended task therefore remains visible to the completion decision.

The native TODO panel displays this list. Updating that panel does not resolve a task. [Task and TODO behavior](task-todo-contract.md) defines the exact projection and recovery rules.

Task tracking also supplies the context for [periodic goal reminders](runtime-lifecycle.md). They help the root agent reconsider its approach using the original purpose and acceptance conditions, without creating another decision authority. When another provider must continue interrupted work, [receiver-initiated adoption](provider-continuity.md) uses the same shared database to transfer unfinished tasks and the worktree lease atomically, while fencing the migrated source.

## Shared data without merged responsibilities

Mutable runtime state uses `.neurath/local/runtime.sqlite3` under the control root derived from Git's common directory. Linked worktrees in the same repository use that common store. Separate clones and separate computers do not share it automatically.

SQLite transactions coordinate state changes that must agree, such as a task result and the session's completion check. Namespace keys, domain codecs, record revisions and digests keep tasks, sessions, messages, claims and memory semantically distinct. A shared database does not make a memory entry an execution receipt or make a peer message a user instruction.

Installation plans, transaction journals, original files for restoration and some private process artifacts retain their own file storage. Do not relocate all private files into the database merely because mutable domain state is canonical there. Old state paths are migration inputs; they are not the current storage layout.

The database opens private files with restrictive modes and rejects symlink paths in its storage chain. Legacy import also binds the original content digest. If a legacy writer changes imported material, drift blocks reuse rather than silently selecting one competing version. [Runtime lifecycle](runtime-lifecycle.md) explains retirement and recovery.

## Distribution and activation

The build includes standalone resources whose hashes are declared in the manifest. Installation produces the target's managed instructions, skill projections, hooks and launchers. Runtime code executes in a persistent environment selected by distribution content, separately from the development `.venv` and the target project's environment. Updating one target does not implicitly move every other target to its runtime.

Installation plans bind exact target paths, before and after bytes, permissions and links. Applying a plan locks and rechecks those inputs before journaled replacement. Conflicting user edits remain available for resolution. Restoration uses the recorded originals and retained runtime, not a reconstruction from today's defaults.

There are three different observations: placement validates installed bytes and links; protocol checks exercise isolated hook subprocesses; native activation requires the real host to invoke the installed hooks and tools. See [host integration](hosts.md) and [validation](validation.md) for their evidence boundaries.

## Context and collaboration boundaries

Project memory keeps cross-session history. The enclave holds bounded recent session facts. Graphify supplies relationships that the agent verifies against current source. Learned strategies and explicitly approved project rules have separate admission and promotion requirements. Session-start memory injection is capped at 3,000 bytes; explicit context retrieval defaults to 12,000 bytes, and learned guidance has its own limit of 12 rules and 6,000 bytes.

A direct child can hold a delegated evaluation role only after its native lineage is verified. Another provider's peer session remains a peer even when it returns a useful review. Provider routes describe supported execution choices; execution and delivery must then be observed. Permission inheritance, model planning and delivery recovery are detailed in [model planning](model-planning-mcp.md) and [collaboration](collaboration-contract.md).

## Where to make a change

Change bundled behavior in `src/neurath/_assets`, not installed `.agents/skills` or `.neurath/rules`. Change admission and dispatch in their host or runtime modules, and keep the schema synchronized with the actual operation. A new installation behavior starts with a failing installer test. An asset change also needs manifest regeneration, required checks, a build and an observed self-install update; these are separate results.

Use [design principles](design-principles.md) to assess a proposed boundary, [capability map](capability-map.md) to find the relevant skill and tool family, and [development](index.md) for the supported development sequence.

# Current context, memory and handoff

Issue #143 separates current enclave facts, sourced historical memories, checkpoint reports and actual session handoff. User-wide SQLite migration `core_0006` adds three tables and a session successor link while preserving sources, unfinished tasks and runners. A historical report never becomes a success verdict.

## Current context and history

Enclaves scope facts (`fact`), assumptions (`assumption`) and decisions (`decision`) by project, session and optional task. Writes and removals require the observed revision: use 0 for creation, then the returned revision. Persistence manages optimistic revisions; individual changes within one atomic request have separate history numbers. A failed change rolls back the entire request, including detailed artifacts.

Removal uses `op: remove`, distinct from setting an empty or null value. Previous values and deletion markers remain in history but never appear as current restored facts. Value objects retain field reassignment protection and read-only Sequence contracts without forced deep immutability.

Current values are limited to 16 KiB of UTF-8 per enclave. A set operation may store a larger `details` body separately, retaining the short `value` and a `memory:<id>` reference. Memory bodies are preserved verbatim up to 1 MiB of UTF-8. Oversized content is rejected rather than silently truncated. Reference strings do not prove the authenticity of external material.

## CLI

These root commands use spakky-typer in a candidate environment whose DB has been explicitly initialized.

- `neurath update-enclave --project-id ID --session-id ID --expected-revision N --changes JSON`: atomically applies a set/remove array. Optional task-id selects task scope; `--changes -` reads JSON from stdin. A set contains key/value/kind/references and optional details.
- `neurath save-checkpoint --project-id ID --session-id ID --content TEXT --reference REF`: stores outcomes, decisions, remaining work and next actions as a report. Repeat reference as needed; `--content -` reads stdin. It does not complete tasks.
- `neurath search-memory --project-id ID --text TEXT`: searches recent memory IDs, optionally limited by session-id/task-id and limit. SQL wildcard characters are treated literally.
- `neurath read-memory --project-id ID --memory-id ID`: reads a selected historical body and its sources. Use session-id instead of memory-id to preview sources, current tasks, runners, enclaves and memory IDs. A checkpoint is not required; preview never changes ownership.
- `neurath resume-session --project-id ID --source-session-id ID --target-session-id ID --expected-revision N --turn-id ID`: connects existing work to the observed target turn. Equal source and target IDs explicitly resume the same execution.

## Handoff and automatic restoration

Cross-session handoff requires observed termination of the source execution and its children, no remaining writer lease and no running phase. Unknown liveness is not termination. An existing target enclave must be read and reconciled first rather than overwritten. Ownership of tasks, runners and enclaves moves within the same project while attempts, sources and change history remain intact. The source successor link prevents old hooks and explicit execution resume from re-enabling duplicate writing.

The [Codex](https://learn.chatgpt.com/docs/hooks) and [Claude Code](https://code.claude.com/docs/en/hooks#sessionstart) `SessionStart` event with `source: compact` returns current context through `hookSpecificOutput.additionalContext`. Startup and resume reuse that path. Restoration contains session-common facts and unfinished-task facts, requirements, source references and runner state. It excludes other sessions and completed/invalidated task enclaves. Empty state returns `{}`. More than 8,000 characters or a failed read produces a failure response without recording successful restoration. Installation must also account for Codex additionalContextLimit and Claude output limits.

Native validation uses separate temporary databases and validation sessions. It does not install the candidate into existing work sessions, user configuration or original databases.

## Graphify integration

`search-memory --graph-directory PATH` invokes the existing `graphify query` command for related code/document relationships. `save-checkpoint --graph-directory PATH` explicitly runs `graphify update`, then adds the verified graph reference to the report. External work runs outside DB transactions.

The adapter backs up graph.json before updating and verifies retained document nodes, relationships, hyperedges and their targets. Recomputed community statistics are excluded from semantic comparisons. Command failure, lost document relationships or malformed output is never success: failed output is retained and the original graph.json is restored. Other Graphify reports may have been regenerated, so reports from a rejected update must not serve as completion evidence. No graph engine or semantic extractor is duplicated.

# Project Newsroom

[Documentation](index.md) · [한국어](../ko/newsroom.md)

Issue #145 provides a project article library and five CLI commands for selectively reading discoveries. Only peers observed in the same project can read, publish, revise, or discuss its articles. `Article` owns revisions, comments, full-body receipts, actual task usage, and headline notifications; these children have no separate repositories.

## Selective reading and source preservation

| Command | Main inputs | Actual effect |
| --- | --- | --- |
| `newsroom list` | `--peer-id`, `--text`, `--after-id`, `--limit` | Lists current titles, revision numbers, seen for that revision, and correction impacts on tasks that actually used it. It neither returns bodies nor records seen. |
| `newsroom read` | `--peer-id`, `--article-id`, `--revision-number`, optional `--task-id` | Prints the selected revision's complete body, evidence, and comments, then records a receipt for that revision. |
| `newsroom publish` | `--peer-id`, `--title`, `--body`, repeated `--reference` | Saves the initial source, evidence, author, and active subscribers' headline notifications together. |
| `newsroom revise` | Publication inputs, `--article-id`, `--expected-revision`, `--reason` | Checks the original author's expected article revision, preserves the old source, and appends the correction. |
| `newsroom comment` | `--peer-id`, `--article-id`, `--revision-number`, `--body` | Comments on a revision actually read. Old comments do not move to the new revision. |

`--body -` reads all standard input. Titles accept up to 200 characters; bodies and comments accept up to 1 MiB of UTF-8 each. Excess input is rejected rather than truncated. Evidence references and correction reasons cannot be blank. Help does not open the database.

`--expected-revision` is the article content revision. The repository's integer `revision` is the optimistic concurrency version for all changes, including comments, receipts, and notification consumption. Stale content revisions, other authors, and cross-project requests roll back their entire transaction.

The body query use case is read-only. The CLI calls internal `RecordArticleReadUseCase` only after JSON serialization and complete stdout output return successfully. Input, serialization, and output failures do not record seen; there is no manual seen command. A database failure after output makes the CLI fail without assuming a receipt was saved. This receipt describes the CLI output boundary, not model comprehension, agreement, or task acceptance.

## Active subscribers and hook headlines

A peer subscribes by including `newsroom` in `SubscribePeerUseCase.topics` from #144. That input replaces the entire topic list, so other retained topics must also be included. Unsubscribing discards not-yet-submitted article notifications in the same transaction. Resubscribing does not revive old headlines. New native peers receive project newsroom headlines by default; existing choices remain unchanged. `newsroom subscribe --disabled` opts the current conversation out while preserving other topics. Ordinary commands resolve the current peer automatically.

Publication and revision snapshot the same project's currently active subscribers. Inactive peers receive no queued news; publication starts neither external messaging nor a provider run. The next eligible actual hook submits only the article ID, current revision, and title once. If another correction preceded the hook, obsolete headlines are not replayed. Each hook submits at most ten headlines; remaining headlines are processed by subsequent hooks while activity continues.

Observed waiting, termination, or cancellation, or an inactive previous peer observation, discards remaining notifications. A new SessionStart other than compact discards past notifications even if termination was not observed. Reconnection alone does not resume a stopped execution. Activity follows the host observations stored by #142/#144; unobserved process termination is not inferred. Generating a hook response is distinct from actual host receipt and inclusion in the next model input.

## Corrections and tasks that actually used an article

Reading and actual usage are separate. `newsroom read --task-id` checks the same project's task definition before output and then links the task, definition number, article revision, and using peer after output. A task definition change during output rolls back both the incorrect usage link and receipt.

After a correction, tasks that actually used older content appear in `ArticleSummary.affected_tasks`, `ReadArticleResult.affected_tasks`, and `GetTaskResult.article_impacts`. Task detail includes the definition used, the used article revision, and the current article revision, keeping unrelated tasks and subsequent requirements distinguishable. Using the latest revision for the same task resolves that link's outstanding correction impact. Reading an old revision again does not undo a previously confirmed current usage. Reading, comments, and agreement do not change requirements, attempt outcomes, or task success.

## Persistence and verification boundary

`core_0010` adds article and owned-history tables without changing existing rows. Downgrade refuses to delete article history and only rolls back an empty candidate schema. Persistence uses framework CRUD, declarative selectin relationships, UUID7, optimistic locking, and `@transactional`.

`tests/test_newsroom.py` exercises actual scanning, DI, SQLite, and CLI behavior for the Newsroom portions of A20/A21/A56 and B17, and runs in shared pre-commit and CI quality checks. It covers stdout, stdin, and commit failures; revision conflicts; cross-project access; actual task impacts; unsubscribe, inactive publication, and reconnection; revision-specific receipts and comments; and preservation migrations. A56's enclave and learning cases belong to their respective tickets. Fixtures and local console execution do not establish installation or activation in a running user host. Do not install this candidate into the user host.

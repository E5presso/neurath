<!-- updated: 2026-09-14 | synced_from: 243400e58ca74c7fd79bcdd86b488953fa743b97 -->

# Return to the investigation without losing its purpose

You return to the saved-filter problem in your web application the next day. The previous agent traced the save request, changed part of the load path, and still needed to verify browser refresh. The useful starting point is that unfinished result, together with the evidence already collected.

> Continue the saved-filter investigation from the previous session. Recover the confirmed findings, changes, and outstanding checks. Keep the original requirement that the selection survives refresh, and verify the current state before editing.

A **session** is the interaction state maintained by Claude Code or Codex. The information an agent can currently use while answering is its **context**. A later session does not automatically contain every earlier exchange, and a long conversation can have its context shortened. Neurath retains selected project **history**—records of earlier requests, observations, and reports—so an agent can recover relevant information instead of treating the work as new.

## What is retained during ordinary work

When supported host hooks are active, Neurath records submitted prompts and observed command events. Before context is shortened, when an agent stops, or when a session ends, it can retain the visible assistant report and a reference description of workflow state. Actual host execution metadata determines whether a command's exit was observed. A successful-looking line in command output is not equivalent evidence.

At session start, the agent receives a bounded selection of project memory and applicable learned guidance. It can search retained history for more as needed. This automatic context is deliberately limited; it does not load the entire history or certify that an earlier report was correct.

For a clearer pause point, ask the agent to record a **checkpoint**, a saved handoff report of the current summary, decisions, next steps, lessons, and status. In the filter example it should distinguish the confirmed save behavior from the still-unverified reload behavior. Supported stopping logic can request this report when it is due. A checkpoint marked completed describes the report's status; it does not complete the user's task or transfer the right to edit.

## Where that memory is shared

Neurath stores these records in a local SQLite database associated with the Git common directory. That is the shared Git storage used by a repository and its linked worktrees. Claude Code and Codex sessions using that same local project can recall records across those worktrees, with source attribution retained.

Separate clones and separate computers do not automatically synchronize this database. Shared memory is also not shared execution ownership: recalling another agent's decision gives reference information, not its permissions or its write ownership record, called a claim. An ordinary new session can use this recall without adopting another session. Adoption is a separate step for taking over a stopped session's unfinished tasks and write responsibility.

Known credential patterns are redacted before persistence, and private reasoning is excluded. Visible assistant reports may be retained. Pattern matching cannot identify every kind of private information, so local memory can still contain private project context. Newsroom article bodies require explicit reading and are not automatically copied into shared recall.

## Recover a stopped session's unfinished work

Sometimes the previous session stopped without writing a checkpoint. The receiving agent can still request **pull recovery**: it gathers the source session's retained information and, when safe, adopts its unfinished tasks. The source does not need to push a handoff first.

The receiver uses task and process records in shared SQLite, project memory, communications, and the exact conversation log registered for that source. This host-written log is a **transcript**; its JSONL format stores one structured record per line. Recovery follows that registered source file, or its exact supported Codex archive relocation. It does not search unrelated conversations for a plausible substitute.

A useful request is:

> Recover the stopped session's unfinished saved-filter work in its original checkout. Inspect what can be recovered, show any missing evidence, and adopt it only after the source and its delegated work have stopped safely.

The receiver first lists or previews the source. The preview is an immutable snapshot owned by the receiver; longer retained details can be read in parts. Listing, previewing, and reading are reference operations and do not transfer ownership. Omission notices matter: a saved preview cannot reconstruct content that was never retained or was omitted from it.

Adoption requires a different verified primary session in the original source checkout. The source must have no unsettled execution, including subordinate agents within its host, independent executions through another host, assignments to existing peers, or commands whose outcomes remain unknown. The source state, transcript observation, and checkout ownership must still match the preview, and the receiver must use its current task state. If something changes, the agent needs a fresh preview. There is no forced takeover path.

When those checks pass, adoption moves the unfinished work and the checkout's write ownership together in one transaction. New receiver-owned task identities preserve the original goals and acceptance; dependencies are remapped. Completed source history keeps its original attribution. The old source is prevented from mutating the migrated work or reclaiming the checkout, even after the receiver later releases it.

The receiver keeps its own native settings. Adoption does not copy credentials, grant permissions, observe an unknown earlier tool result, or recreate unsaved provider content. It supports up to 64 unfinished tasks in an adoption; larger or unsettled sources must be handled within the supported bounds. It also cannot guarantee that every nuance of the prior conversation was captured. The agent still needs to inspect the current files and test the remaining refresh behavior.

Exact paging limits, source checks, and recovery inputs are in the [memory reference](../contributing/memory-reference.md). Do not use another session's remembered write claim as a substitute for adoption.

## Learn from a correction without overstating it

During the same investigation, suppose a verification command fails because it uses the wrong project environment. The agent corrects the environment and repeats the same verification operation successfully. There are three different ways that experience can be used.

A **reflection** is the agent's account of what went wrong and what helped, saved in a report or checkpoint. It is useful context, but it remains an interpretation.

**Execution learning** uses observed failure and recovery evidence. Neurath can automatically record a candidate when a changed successful command follows a matching failure in the same session, worktree, and command family, tied to the registered checks and their success conditions, called the project verification contract. Running a different test or receiving an unrelated successful output does not establish that recovery.

The candidate becomes trial guidance after the source session passes the configured project check. It becomes active guidance only after another session actually receives that guidance, successfully uses the same recovery, and passes the matching check. At session start, applicable trial or active guidance can be supplied to help later work. This process does not require you to turn learning on for each failure, but it does require real evidence before promotion.

A recovery that fails again or is followed by a failed trial check can be reverted. A changed verification contract in the originating worktree makes the old guidance stale; a change in an unrelated linked worktree does not do so by itself. At a stopping point, Neurath can request an authorized registered check for due learning, followed by an accurate handoff. If the check is unavailable, forbidden, failed, or deferred, the result remains unvalidated as appropriate. Learning does not expand permissions, launch unattended sessions, or repeat experiments until something turns green.

An **approved project rule** is a lasting repository instruction. To turn recurring experience into one, ask for `memory-to-rules`: the agent prepares reusable wording, removes private details, and follows the authority for the requested repository change. A proposal-only request makes no repository change. Automatic learning alone does not edit source files or project rules, and learned guidance remains subordinate to current user instructions, repository rules, and permissions.

When you return to the filter investigation, the result should be less repeated discovery and a more accurate next step. The original requirement still decides completion: the saved selection must survive refresh. [Working with agents](agents.md) explains how the source work may have been divided; [project conventions](profiles.md) explains the verification contract used by learning.

[한국어](../../ko/usage/memory.md)

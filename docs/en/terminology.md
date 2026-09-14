<!-- last_updated: 2026-09-14; synced_from: 243400e58ca74c7fd79bcdd86b488953fa743b97 -->

# Look up a term

[한국어](../ko/terminology.md) · [Usage guide](usage/index.md)

Use this page when a report or reference uses an unfamiliar word. If Neurath is new to you, first read the [saved-filter walkthrough](usage/start-here.md), which introduces these ideas as they become useful.

## Requested work and its result

| Term | Meaning in ordinary work | Technical name or boundary |
| --- | --- | --- |
| Goal | The outcome the user wants, such as a saved selection surviving refresh. | Recorded as a task's `goal`; an investigation method does not replace it. |
| Acceptance criteria | Observable conditions for deciding whether the requested outcome was achieved. | Task `acceptance`; success needs evidence relevant to those conditions. |
| Task | Requested work with its source, acceptance criteria, dependencies, and outcome. | Task ledger; `task_define`, `task_start`, `task_resolve`. |
| TODO | The host's visible list of task rows. | A projection of the task ledger, not a separate completion authority. |
| Goal reminder | Context that brings the request and relevant unfinished work back to the agent's attention. | Automatic hook-delivered reference context; does not change task state or certify success. |
| Outcome | The owner's recorded account of how the task ended. | `succeeded`, `failed`, or `invalidated`; terminal does not always mean successful. |
| Receipt | A record of a particular event. | Its meaning depends on the event observed; a delivery receipt cannot prove a tested fix. |
| Provenance | Where a fact or requirement came from. | Source attribution retained with tasks, reports, and observations. |

## Who is working and where

| Term | Meaning in ordinary work | Technical name or boundary |
| --- | --- | --- |
| Host | The coding-agent application that supplies native session and tool events. | Claude Code or Codex. |
| Session | One native interaction state in a host. | A resumed session may retain work; a new session has a distinct identity. |
| Root | The primary actor of a session. | A verified native root owns its task mutations. |
| Native child | An agent directly subordinate to the current session. | Host-attested direct parent/child lineage; preparation alone is not a running child. |
| Peer | Another participating agent session that can exchange findings or accept an assignment. | Discovery and message acceptance do not grant ownership of its files. |
| Provider session | A separately launched native session used for assigned work. | An independent native root with separately observed activation, settings, model, and ownership. |
| Worktree | The Git checkout in which a session works. | A checkout identity; linked worktrees can share local project state. |
| Claim / lease | The current right to write in a worktree. | `worktree_claim`; release uses the actual returned lease epoch and `fencing_token`. |
| Fencing token | A value used to reject writes or releases from an outdated owner. | Ownership control data; a copied actor name or old claim report cannot substitute for it. |
| Execution policy | The supported permissions and tool/hook rules under which a provider runs. | `inherit` follows the immediate creator; explicitly chosen `target-native` uses the destination's existing defaults. |
| Model selection | Which model is planned for an assignment. | `selection.model="inherit"` is separate from execution policy and must be checked against actual execution. |
| Newsroom | A local place to publish findings that may help other active peers. | Headline notifications are automatic for active peers; article bodies require explicit `newsroom_read`. |
| Acknowledgement | Confirmation that a recipient read a message's full body. | ACK is distinct from accepting an assignment and from completing it. |

## Information carried forward

| Term | Meaning in ordinary work | Technical name or boundary |
| --- | --- | --- |
| Context | Information available to an agent for its current judgment. | May contain current observations and recalled reference material. |
| Project memory | Retained, attributed project history that another local session can consult. | Local SQLite state selected by the Git common directory; no automatic synchronization across clones or computers. |
| Checkpoint | An agent's handoff report of decisions, next steps, and remaining work. | `memory_checkpoint`; a report marked `completed` does not resolve tasks or release a claim. |
| Transcript | Recorded native conversation and tool activity. | Recovery reads the registered source record, removes private reasoning and known credential patterns, and preserves attribution and omissions. |
| Memory pull | A receiving session retrieving the source's retained work. | `memory_pull` list/preview/read are reference-only; a final source checkpoint is not required. |
| Adoption | The verified transfer that lets a receiver continue unfinished work. | `memory_pull` adopt transfers unfinished tasks and the worktree lease atomically after source execution settles, and fences the migrated source. |
| Snapshot | A retained view of source state used to inspect a proposed takeover. | Immutable receiver-owned preview; source changes require a new preview before adoption. |
| Enclave | A bounded record of the session's current facts. | Revision/digest-controlled state; historical memory alone cannot overwrite current facts. |

## Retaining a better way to work

| Term | Meaning in ordinary work | Technical name or boundary |
| --- | --- | --- |
| Reflection | An explanation of an experience and a possible lesson. | An agent report; it is not automatically validated guidance. |
| Recovery learning | Retaining an observed successful correction to the same failed operation. | Candidate → trial after the source project check → active after a different exposed session repeats the recovery and matching check. |
| Withdrawn or stale guidance | A lesson that should no longer be relied on in its former state. | Regression/check failure can produce `reverted`; changed verification can produce `stale`. |
| Memory-to-rules | Proposing a durable project instruction from recurring observations. | Public skill `memory-to-rules`, source ID `promote-memory`; repository changes require authorization and privacy review. |
| Skill | A reusable procedure for a kind of work. | A public skill name selects a procedure; the name alone supplies neither task intent nor permission. |
| Verification contract | The repository's configured definition of a project check. | Used to match recovery evidence; ordinary source work still uses native editing and test tools. |

For exact arguments and state transitions, use the [task tool reference](contributing/task-tools.md). For the concepts in use, return to [collaboration](usage/agents.md), [memory](usage/memory.md), or [skills](usage/skills.md).

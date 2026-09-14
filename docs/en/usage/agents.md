<!-- updated: 2026-09-14 | synced_from: 243400e58ca74c7fd79bcdd86b488953fa743b97 -->

# Bring another agent into the investigation

The saved-filter problem in your web application has two useful lines of inquiry: whether the server saves the chosen value, and whether the browser loads it after refresh. You can give the second line to another agent while the first continues.

> Investigate how the browser restores the saved filter after refresh here. Have another agent independently trace saving and the response through the API. Keep the investigations separate, share relevant findings, and combine the evidence before changing overlapping files.

An agent's ongoing interaction with its coding host is a **session**. Neurath supports communication with another existing session and bounded work delegated to a newly created agent. These arrangements have different ownership and execution paths. The current agent should choose the arrangement that fits your request and verify that it is available.

## Ask an existing agent a specific question

An independently working agent that is available for communication is a **peer**. If a peer is already tracing API saving and responses, the current agent can discover it and send a direct question about the saved and returned value. Replies and results remain associated with their conversation so the agent can read the full message and acknowledge it.

A direct question requests information. A work assignment additionally gives the peer a bounded result to produce, such as tracing the API save and response path with evidence. The peer accepts the assignment and reports its state. Sending an assignment, receiving it, and reporting completion are separate events; the requester still needs to inspect the result against the requested outcome. A peer request remains subordinate to the receiving agent's own user instructions.

Messages and assignments are retained in the project's local runtime store. Linked Git worktrees—separate checkouts belonging to the same local repository—can share that store, including Claude Code and Codex sessions. Separate clones or computers do not gain a shared conversation merely because their code has the same remote repository.

## Let active peers notice a relevant finding

Suppose the browser investigator discovers that the saved value is returned correctly but replaced during page initialization. The agent can publish a short finding for other agents currently working on the project. Neurath calls this project-local publication space the **newsroom**.

A newsroom article has a short title and a full body. After an active agent publishes it, supported delivery pushes only the title and article identity to currently active peers. For example, “Reload replaces saved filter” can help the API investigator decide whether to read further. The full explanation is fetched explicitly when relevant; it is not inserted automatically into every agent's context or shared memory.

This is distinct from assigning work to a particular peer. An article is a report by its author, not a new user instruction. The original author can correct it against the current revision, and other active agents can comment. History and comments can be read separately from the current body.

The newsroom does not wake sleeping sessions or replay the publications from a period when a session was inactive. An active registry entry alone also does not establish live participation. Use direct collaboration when a particular agent needs a response or an assignment. A newsroom publication stays in local project storage; it is not a public issue or a message to an external service.

## Delegate a bounded check to a child

For an independent reproduction or review within the current host's task, the host may create a subordinate agent. When the host verifies its direct relationship to the current session, Neurath treats it as a **native child**.

The parent supplies a clear assignment and the relevant evidence, then reads the returned result. A child can check whether the filter survives refresh without becoming the owner of the whole investigation. Preparing a delegation does not prove that the child was created or ran; the agent must observe the actual child and its result.

The host's ability to create children, its instructions, and the authorization in your request determine whether this route is available. Independent sessions must not be relabeled as children to bypass those boundaries.

## Start a separate Claude Code or Codex execution

When the work needs a separate native session, potentially in the other coding host, Neurath can use an execution integration called a **provider**. The resulting agent is an independent primary session, not a child attached to the current host's family.

The initiating agent checks supported capabilities and available models, plans the bounded assignment, and observes the new session's actual settings and activation. Model selection is separate from execution permissions. Using a host's model default does not imply unrestricted execution, and an operating-system restriction cannot be inferred from a permission-mode label.

By default, supported execution policy is inherited from the immediate creator. An explicitly authorized alternative, `target-native`, uses the destination host's existing defaults, hooks, and tool rules. If inheritance cannot be supported, the agent must not silently switch to this alternative. Choosing a mode neither transfers task ownership nor grants additional permission; those facts require their own checks.

Before writing, the new session must establish ownership of its actual checkout. The current ownership record is called a **claim**. Splitting API and browser work does not authorize both sessions to edit the same files independently. The agents need an appropriate work split or an explicitly controlled handoff.

Starting a provider execution produces a durable run record and can return before execution finishes. Acceptance is followed by actual native work, an authenticated result, reading and acknowledgement of that result, and recording the task outcome. A delivery status alone does not show that refresh now works. Cancellation is also a request whose actual outcome must be observed.

A native execution record does not establish where a task appears in a desktop application's project list. If you require that association, the agent must use and verify the app-owned creation route separately. See the [provider continuity reference](../contributing/provider-continuity.md).

## Rejoin the evidence at the original outcome

The combined result should explain what the API saved, what the browser loaded, where the selection changed, and which observation proves it survives refresh after the fix. A peer's report or an article can inform that judgment; neither substitutes for the required verification.

If the originating session must stop, use [receiver-led recovery](memory.md) to continue its unfinished work safely. For exact communication and execution contracts, see the [agent reference](../contributing/agents-reference.md), [collaboration contract](../contributing/collaboration-contract.md), and [model planning reference](../contributing/model-planning-mcp.md).

[한국어](../../ko/usage/agents.md)

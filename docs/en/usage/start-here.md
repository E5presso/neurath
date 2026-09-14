<!-- last_updated: 2026-09-14; synced_from: 243400e58ca74c7fd79bcdd86b488953fa743b97 -->

# Follow a bug without losing the task

[한국어](../../ko/usage/start-here.md) · [Usage guide](index.md)

You ask a coding agent to fix a bug. It investigates, tries an approach, asks another agent to check something, and eventually needs a fresh session. Each transition can lose something: the behavior you wanted, a failed approach, a useful finding, or who is allowed to edit the files next.

Neurath is a harness around Claude Code and Codex that keeps those things available. It connects the requested outcome to recorded work and explicit responsibility. The agent still has to reason about the bug and verify the result.

This page follows **a hypothetical web application you are developing**. Its saved filter disappears after a browser refresh. The application and bug are teaching examples, not Neurath features; this walkthrough does not create an application.

## Begin with the behavior you want

A **goal** is the outcome you want. **Acceptance criteria** are the observations that would show you got it. A **task** records that requested work and its acceptance criteria, along with dependencies and the eventual outcome.

You tell the agent:

> In the web app I'm developing, the filter I saved disappears after refreshing the page. Reproduce the problem, find and fix its cause, and verify that the saved selection survives refresh. Keep the existing interface.

The goal is a filter that survives refresh. The acceptance criteria are a reproduced failure, a supported explanation of its cause, the corrected behavior after refresh, and preservation of the interface. Neurath keeps those attached to the task while the agent investigates. A checked box or a successful unrelated test would not establish those results.

A **session** is one running conversation with a coding agent. Its **worktree** is the Git checkout in which it works. When several sessions are involved, Neurath records a **claim**: which session currently holds the right to write in that worktree. The agent checks this before editing, so finding useful information and owning the next edit remain distinguishable.

## Keep the investigation connected to the request

Suppose the agent reproduces the disappearing filter, then spends several tool calls considering a broader redesign of filter storage. That may be interesting, but it has not yet answered your request.

Neurath automatically provides **goal reminders** during eligible work. A reminder brings the original request and relevant unfinished tasks back into the agent's context. Once a reminder is due, it is delivered at the next eligible native activity or hook event, rather than by an independent timer. A reminder also appears immediately before the agent defines, starts, or resolves a task. You do not have to ask for each one.

Here, the agent should use the reminder to compare its investigation with the acceptance criteria. It can narrow the next step to finding where the saved value is lost, explain any necessary change of approach, and retain the refresh check. The observable result is an investigation still directed at the saved-filter bug. The reminder does not itself detect a wrong design, verify a fix, or change the task's state.

## Ask for one useful second investigation

The first agent sees two possibilities: the save request may not persist the value, or the page may fail to restore a correctly saved value when it reloads. Those questions can be investigated independently.

You can request:

> Have another agent check whether the saved filter is present in the API response. Keep the reload investigation with the current agent, and bring the findings together before changing the fix.

A **peer** is another participating agent session. The current agent can send a bounded assignment directly to an available peer. It can also use a helper attached to the current conversation or a separately launched Codex or Claude Code session. Those routes have different execution relationships, so the agent checks the actual environment, permissions, and editing responsibility for the route it uses. Preparing the helper does not mean the investigation has run. The [collaboration guide](agents.md) explains these choices and their technical names.

Suppose the second agent reports that the saved value is present in the API response. The first agent needs the supporting details before concluding that reload handling is responsible. A direct reply can carry that report. When the finding is useful to other active peers, the author can also publish it in the **newsroom**, a local place for shared findings. Active peers automatically receive the headline; they read the article body explicitly when it is relevant. Inactive peers are not woken, and the body is not automatically copied into every conversation.

The receiving agent reads and acknowledges the result, compares it with its own evidence, and records the bounded assignment's outcome. A message marked accepted or delivered only describes delivery. Your original task still needs a fix and a refresh check. See [working with other agents](agents.md) for choosing and following these routes.

## Continue in a fresh session

Now suppose the current session must stop before it finishes the fix. **Context** is the information an agent can use now. **Memory** is retained project history that a later session can consult. A **checkpoint** is an agent-written handoff report: what was decided, what remains uncertain, and what should happen next. A **transcript** is the recorded conversation and tool activity from a session; it can contain detail a summary leaves out.

You can ask:

> Preserve the API finding, the reload investigation, the changes already made, and the checks still missing. Continue the same saved-filter task in a new session.

When the native host hooks are active, Neurath automatically records supported observations such as prompts, command outcomes, and handoff reports at lifecycle events. It recalls a bounded amount of retained context when a new session starts. The agent can request additional history and write a checkpoint when needed. An agent's report remains a report; it does not turn an unobserved check into an executed check.

A normal new session can use automatic recall and additional history queries without taking over another session's work. When it must take responsibility for a stopped session's unfinished tasks and files, the receiving session uses **memory pull**: it retrieves a snapshot of the source's retained work, with relevant transcript material when available. The source does not have to produce a final checkpoint or push its context first. Listing, previewing, and reading that material are reference steps; they do not transfer ownership.

Before the receiver edits, the source must have stopped executing and its children, provider jobs, and peer assignments must be settled. Neurath checks that the snapshot and current state still match. Adoption then transfers the unfinished tasks and worktree lease together, preserves their dependencies, and prevents the migrated source from resuming writes. The receiver continues with its own native settings. A changed source requires a fresh preview; there is no forced takeover shortcut.

In our example, the new session should be able to explain which API evidence it recovered, which reload change is present, and which acceptance checks remain. It verifies the actual checkout before continuing. Missing or unrecorded material stays missing; Neurath does not promise perfect recall or perfect understanding.

This history is shared locally by Claude Code and Codex sessions and linked worktrees belonging to the same Git common directory. Separate clones and computers do not automatically synchronize. Known credential patterns are redacted and private reasoning is excluded, but retained project context can still be private. The [memory guide](memory.md) explains what is retained, the bounded reads, and takeover conditions.

## Learn from a real recovery

As the receiving agent runs the saved-filter regression test, suppose its test command fails because it was launched from the repository root while the test runner expects the web-app directory. It corrects the invocation's working directory and reruns **the same selected test** successfully. Choosing a different, easier test would not show that this failure was recovered.

**Reflection** is the agent explaining what happened and what it would do next time. Neurath's **recovery learning** goes further only when it has observed evidence: a failed command followed by a changed successful command in the same session, worktree, and command family, tied to the project's verification contract.

That creates a candidate, not an established rule. If the configured project check passes in the source session, the candidate becomes trial guidance. A different session that has been exposed to the guidance must successfully use the same recovery and pass the matching check before it becomes active guidance. If the recovery regresses or the check fails after trial use, the guidance is withdrawn; a changed verification contract makes it stale.

These stages occur through observed work. Neurath does not create extra sessions or unrelated experiments to manufacture evidence. Due learning checks can be requested at stopping time within existing authority; unavailable or forbidden checks leave the observation unvalidated. This updates retained guidance, not the model's training or the agent's permissions.

You can separately ask:

> Review whether this lesson belongs in our project instructions. Propose a reusable rule and remove private incident details before any approved change.

This asks for a durable project rule based on recurring observations. Changing those instructions requires authorization and privacy review. It is separate from both reflection and automatically validated recovery guidance. The [skills guide](skills.md) explains the workflow for turning memory into rules.

## Return to the saved-filter result

In this hypothetical example, the reload investigation finds that page initialization overwrites the restored selection with the default. The agent corrects that order. It saves a selection, refreshes the page, and observes that the same selection remains; the existing controls and layout are preserved. Its report connects those observations to the original failure and explains the change.

The session change and second investigation were ways to reach that result. The final evidence must still show that the saved selection survives refresh and explain how the existing interface was checked. If some acceptance evidence is missing, that work remains unfinished even if the handoff succeeded or a test command passed.

The relationships are now concrete: the **task** holds the requested outcome; **goal reminders** keep it visible; **collaboration** adds bounded findings; **memory and checkpoints** retain useful context; **adoption** establishes who can continue the work; and **recovery learning** retains a verified way past a recurring execution failure. None replaces the final observation your request requires.

## Apply the approach to your project

Start with [installation](installation.md) and ask your agent to prepare Neurath for your repository and chosen host. It should preserve existing instructions, hooks, permissions, and dependencies, and distinguish installed files from a working runtime and observed host activation.

Then describe one real task in terms of the behavior you want and the evidence that would satisfy you. Use [project setup](profiles.md) to connect the repository's existing instructions and checks. Ask for another agent, a checkpoint, or a takeover when the work calls for it; those actions follow the authorized task. Hook-driven capture, recall, reminders, and qualifying recovery observations happen automatically only where their required host participation is active.

Neurath helps retain context and responsibility. It does not guarantee semantic correctness, invent missing verification, expand permissions, or silently turn an unfinished goal into success. After this walkthrough, the [usage guide](index.md) leads to particular operations, and the [terminology lookup](../terminology.md) maps the words you have learned to technical names you may see in reports.

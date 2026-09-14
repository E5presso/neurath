<!-- date: 2026-09-14; synced_from: 655c8768709e59b5e5012bab0adc4d888e3e7fa5 + current working-tree facts -->

# Resume from recorded decisions

[한국어](../../ko/usage/memory.md)

Ask the agent to recall a previous decision or unfinished work, then compare that history with the project as it stands now.

> What did we decide about this change, why did we choose it, and what remains unfinished? Check the current implementation before continuing.

Project memory records goals, decisions, observed requests and commands, handoff results, remaining work, and lessons. Later sessions automatically receive relevant history at session start and can look up more detail when you ask. A useful answer separates the saved decision from what the agent has just checked.

## Continue after an interruption

Records already saved locally survive a session interruption. This gives the next session a starting point: what was attempted, what was reported, and where work stopped. Work that was never observed or saved cannot be reconstructed.

A handoff note describes the previous agent's progress. The new session checks the current source and your latest request before acting; old approval or workspace ownership does not transfer with the note.

Linked worktrees in the same local Git project share memory. Separate clones and computers do not synchronize automatically. If you are moving between them, do not assume the other location already has the recorded context.

## Continue with another provider

If a provider runs out of quota before finishing, open a receiving session in the same original worktree and ask:

> Pick up the unfinished work from the stopped Codex session. Read its saved context, check where it stopped, and keep your own existing settings. Confirm the ownership transfer before editing.

The receiving agent retrieves the project's saved tasks and memory, with available context from the exact registered conversation log. The stopped agent does not need to make a final checkpoint or send its context. The receiver first previews the source; taking ownership is a separate step that requires the source's tools, children, and delegated work to be settled.

After adoption, the receiver has its own unfinished-task records and the right to edit that worktree. Completed source history keeps its attribution, and the migrated source session cannot resume writing or reclaim the workspace. This prevents both sessions from continuing the same writes. A preview or ordinary memory lookup alone does not transfer anything.

Recovery is limited to persisted data. Missing provider records cannot be reconstructed with certainty, and saved text does not prove that a tool succeeded. The [continuity reference](../contributing/provider-continuity.md) covers preview, adoption, and recovery limits. The same checks described below still apply before an observed recovery becomes learned guidance.

## Learn from a recovery that actually worked

Memory and learning operate during normal active sessions without a separate activation step. Suppose a test failed because it was launched outside the project's intended environment. Running the same selected test through the proper environment can provide a recovery example. Choosing an easier or different test would not establish recovery of the original failure.

A successful alternative first needs the source session's configured project check to pass. Another session must then use that same recovery and pass the matching check before it becomes active guidance. This gives the agent evidence beyond its own initial reflection.

You can ask:

> Why are you suggesting this recovery? Has another session used it successfully, and are the project's checks still the same?

If the recovery or its following check fails, the guidance is withdrawn. Changed verification conditions can make an earlier lesson stale. When a needed check is unavailable or prohibited, the lesson remains unvalidated with the reason recorded.

Learning improves execution guidance during your work. It does not itself change source code, project rules, or permissions, and it does not start unattended sessions. If a repeated lesson should become a project rule, ask for the separate review described under [Available skills](skills.md).

## Keep project history local

Common credential patterns are redacted, but local records may still contain private project context. Private reasoning is excluded; reports visible to the user may be recorded. A peer article is not automatically copied in full into memory or sent upstream.

[Reporting and contributions](reporting.md) explains the separate choice and content review for external publication. Storage layout, context limits, and learning validation details are covered in the [contributor documentation](../contributing/index.md). [Agents and shared work](agents.md) describes message delivery when work spans sessions.

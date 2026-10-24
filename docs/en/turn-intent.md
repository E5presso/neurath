# Current-turn intent and preserved work

Hooks preserve the user's original text. They do not classify its purpose with keyword matching or an extra model call. The agent reads the original and connects its meaning and current-turn scope only when existing unfinished work or evaluation would otherwise be affected. Users do not need to manage modes or internal identifiers.

```sh
neurath context show
neurath context show --section sources
neurath session interpret --kind status --pause \
  --reason 'The current original requests a status response and excludes execution in this turn.'
```

`session interpret` selects the last original observed in the current turn by default; `--source-id` can select another original from that turn. `--kind status` covers status questions, explanations, and same-work turn control that do not change the required result. Real new requirements and mixed requests remain `--kind prompt`. Existing Memory records preserve the reason, previous kind, and source reference without rewriting the original text, author context, or provenance. Requirements already linked to task definitions cannot be changed to status to evade completion checks.

`--pause` records the current execution's `turn_control` cause and returns control for this turn. The first Stop does not demand continued work, and repeated Stop does not cancel or complete original tasks or phases. It does not fabricate an external dependency wait or block all ordinary tools. The next actually observed user turn reconnects execution while keeping the same work; authorized resumption in the current request uses existing `session resume`. An agent distinguishes whether a status request also asks work to continue. Simple conversation without affected existing work requires no new task, workflow, or interpretation procedure.

Independent evaluation continues receiving original text including status, latest corrections, interpretation reasons, full TODO, and omitted requirements. Status and historical summaries do not change the candidate fingerprint as new result requirements. A new prompt remains in the fingerprint and evaluation input even before it is assigned to TODO. Related requirement revisions and actual artifact changes still invalidate earlier evaluation and return unmet work to the same original task. An agent's mistaken interpretation is not promoted into user authority or independent acceptance.

## Session addresses and tool cwd

When an observed provider/native address identifies one session, tools can query its original work from another directory. A read does not create or merge projects or sessions or relocate the stored session. `context show` reports `host.session_directory` for the stored session location, `host.invocation_directory` for the actual caller, and `project_id` for the original work scope.

If the same address has actually been observed in several projects or hosts, the current project directory narrows the candidates. Remaining ambiguity requires the observed provider and project ID through `context show --session ... --provider ... --project-id ...`. The agent selects from already observed context without merging unrelated projects or inventing native identity.

`core_0016` marks compatibility with the new `turn_control` execution cause. Physical source and task tables remain intact, while Alembic compatibility checks prevent older shared-database clients from misreading the new state. Downgrade refuses to discard executions retaining that cause. Installation and transition follow existing [preserving distribution](distribution.md).

Actual CLI/SQLite regressions cover first-Stop control return, unchanged TODO/run and resumption, different cwd and reused observed addresses, evaluation reuse after status, and invalidation by new omitted requirements or changed artifacts. The agent remains responsible for interpreting original meaning; these tests do not establish native model judgment quality or actual host activation.

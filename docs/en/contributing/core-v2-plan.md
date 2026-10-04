# Core replacement implementation plan

[한국어](../../ko/contributing/core-v2-plan.md) · [Core specification](core-v2-spec.md)

The replacement source and removal of the previous core are implemented. The source candidate is 0.2.3. Installation and actual activation of an existing host are separate operations; a source commit does not change a running immutable installation.

## Implemented boundaries

- Task owns user acceptance, ordered SkillRuns, attempts and assignments. Failed attempts retain the original goal. Phases cannot be skipped and normal Stop requires owned obligations to be settled.
- Native actor identity is independent of checkout location. Writer leases coordinate changes; reads and failure reports remain available without writer ownership.
- Subagent, independent session and cross-provider execution are explicit choices. Worker, reviewer and executor are roles. Native handback checks the recipient’s report obligation without waiting for parent acceptance.
- Original input spans, actual tool results and attributed reports remain distinct. Review preparation requires an explicit checkout and captures its source snapshot. Changed sources cannot reuse an earlier review.
- One SQLite store holds work state. The installer imports retained v1 goals, dependencies and leases during an offline file transition, preserves the original database and recovers interrupted file installation.
- All 33 distributed skills have ordered definitions. Native tools perform edits, checks and provider execution. The old runtime, host/agent control packages, script engines and obsolete provider orchestration are removed.

## Object responsibilities

`Task` owns controller selection, role compatibility, assignment participation, ordered skill progress and final acceptance. `Assignment` owns binding, result reporting, acceptance and terminal transitions. These immutable domain objects depend on neither persistence nor host payloads.

`Core` composes concrete collaborators and owns command validation, authentication, idempotency and the transaction boundary. `TaskCommands` and `AssignmentCommands` translate named requests into domain operations. `Provenance` retains sources and validates evidence against its Task, attempt, checkout and original source kind. Reviewer independence includes implementation participation across project Tasks.

`SessionLifecycle` observes actor activation and interruption, preserves unfinished work and projects native TODO/Stop results. `WorkspaceOwnership` coordinates checkout writers. `NativeInvocations` binds a native call to its exact request and closes its lifetime. `CheckObservations` retains direct registered-check observations. `HookAdapter` translates host events and delegates to these collaborators; it does not construct domain transitions.

Collaborators handling one command share its `Transaction`. Assignment reports save source, evidence and Task revision together; an interrupted save rolls all of them back. External publication reads occur before the write transaction and authentication is checked again when recording the result. Retrying a successful command returns its original result. Concrete methods and explicit routing keep these paths visible without a generic command bus or inheritance hierarchy.

## Verification status

The 0.2.2 baseline passed 472 package/installation tests and 158 isolated core contract tests. The 0.2.3 object-responsibility refactor passed its own full gate: 477 package/installation tests and 163 isolated core contract tests. Its wheel passed independent imports of 33 core modules and installation/reinstallation/removal in three repository types; actual setup and self-installation checks also passed. An independent object-design review found no unresolved actionable finding. A real Claude session received one unfinished-task Stop rejection and completed the same Task afterward. Actual Codex activation remains pending project/hook trust. Workflow enforcement is limited to ordered transitions, completion evidence, assignment settlement and writer coordination. Shell classification, terminal-input interception, per-phase tool permissions and the bypass switch were removed. Independent review revalidated interrupted session/executor recovery, literal editor destinations, review freshness, required independent review and result attribution. The built wheel passed independent imports with source checkout access denied, and installation/reinstallation/removal across three repository types. The actual setup bootstrap also passed user-file preservation and self-installation checks.

Actual Claude observations include ordered-phase rejection and continuation after an unfinished-task Stop in earlier frozen candidates. An earlier frozen candidate additionally passed native subagent creation, source reading, attributed review, native handback, owner acceptance and ordered phase completion. The failed handback attempt and successful retry retain the same Task ID and separate attempts.

Actual Codex validation remains pending project/hook trust for the isolated candidate. Protocol fixtures are not substituted for this result. Existing production activation, merge and public release must be reported independently when they occur.

## Test replacement

Tests coupled to removed internal structures are retired with those implementations. Required behaviors live in `tests/core`: Task/phase/Stop and rework, transactional revisions, source and approval provenance, writer ownership, three delegation choices, actual check results, review freshness, native return and legacy data preservation. Installer, update, reporting, wire transport and learning tests remain. The complete suite and source integrity checker are the release gates; a passing subset is partial evidence.

The 0.2.2 wheel independently passed imports, three repository installation/reinstallation/removal cases and the real setup/self-installation validation. Its actual Claude root session attempted one normal Stop with an unfinished Task, received the native rejection and completed that same Task after reading the requested source. This validates completion responsibility without a shell-permission classifier. Actual Codex activation remains unverified pending the host's project/hook trust decision.

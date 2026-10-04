# Core replacement implementation plan

[한국어](../../ko/contributing/core-v2-plan.md) · [Core specification](core-v2-spec.md)

The replacement source and removal of the previous core are implemented. The release candidate is 0.2.1. Installation and actual activation of an existing host are separate operations; a source commit does not change a running immutable installation.

## Implemented boundaries

- Task owns user acceptance, ordered SkillRuns, attempts and assignments. Failed attempts retain the original goal. Phases cannot be skipped and normal Stop requires owned obligations to be settled.
- Native actor identity is independent of checkout location. Writer leases coordinate changes; reads and failure reports remain available without writer ownership.
- Subagent, independent session and cross-provider execution are explicit choices. Worker, reviewer and executor are roles. Native handback checks the recipient’s report obligation without waiting for parent acceptance.
- Original input spans, actual tool results and attributed reports remain distinct. Review preparation requires an explicit checkout and captures its source snapshot. Changed sources cannot reuse an earlier review.
- One SQLite store holds work state. The installer imports retained v1 goals, dependencies and leases during an offline file transition, preserves the original database and recovers interrupted file installation.
- All 33 distributed skills have ordered definitions. Native tools perform edits, checks and provider execution. The old runtime, host/agent control packages, script engines and obsolete provider orchestration are removed.

## Verification status

The full source gate passed 512 package/installation tests and 198 isolated core contract tests. Independent review findings concerning terminal input, review freshness, mandatory independent review, request error isolation and native handback were corrected and revalidated. The built wheel passed independent imports with source checkout access denied, and installation/reinstallation/removal across three repository types. The actual setup bootstrap also passed user-file preservation and self-installation checks.

Actual Claude observations include ordered-phase rejection and continuation after an unfinished-task Stop in earlier frozen candidates. The current candidate additionally passed native subagent creation, source reading, attributed review, native handback, owner acceptance and ordered phase completion. The failed handback attempt and successful retry retain the same Task ID and separate attempts.

Actual Codex validation remains pending project/hook trust for the isolated candidate. Protocol fixtures are not substituted for this result. Existing production activation, merge and public release must be reported independently when they occur.

## Test replacement

Tests coupled to removed internal structures are retired with those implementations. Required behaviors live in `tests/core`: Task/phase/Stop and rework, transactional revisions, source and approval provenance, writer ownership, three delegation choices, actual check results, review freshness, native return and legacy data preservation. Installer, update, reporting, wire transport and learning tests remain. The complete suite and source integrity checker are the release gates; a passing subset is partial evidence.

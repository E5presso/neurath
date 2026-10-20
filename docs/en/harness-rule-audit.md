# Harness rule audit — 2026-10-20

[한국어](../ko/harness-rule-audit.md)

Baseline: `62f5f3298dddad7195d98799cae1f2940725b51c`. Direct user instructions and original PR #154/#155 inline reviews and review bodies are the authority. Agent-written instructions, replies, and test expectations are not independent user authorization. This audit removes unsupported automatic denials rather than declaring every design appropriate.

All **33** previous AST diagnostic categories were examined. **11** remain with confirmed scopes; **22** custom diagnostic categories were removed. Actual behavior and current contract tests still enforce the supported requirements. Product domain/application implementations and their existing behavior tests are unchanged.

## Findings

Global Any/cast/Literal bans, Core/UoW/database/transport name blacklists, repository method/argument whitelists, compulsory result suffix/frozen/DTO rules, a standard-library allowlist, general suppression bans, the Ruff ANN401 ban on Any annotations, and Korean character quotas were unjustified expansions. Protocol exclusion, explicit abstract contracts and registered framework components, standard Korean documentation, framework reuse, current dedicated DTO colocation, data preservation, and full statement/branch coverage with zero exclusions remain.

## Complete diagnostic inventory

Each category below links its original intent to the corrected enforcement scope. The paired Korean edition retains the detailed Korean review context. [PR #154](https://github.com/E5presso/neurath/pull/154/files) and [PR #155](https://github.com/E5presso/neurath/pull/155/files) contain the source reviews; later user corrections take precedence.

| Diagnostic | Decision | Original intent and reference | Corrected scope |
| --- | --- | --- | --- |
| ABSTRACT_METHOD | Retain, scoped | Explicit abstract port methods — [PR154#4280330548](https://github.com/E5presso/neurath/pull/154#discussion_r4280330548) | Check declared ports only. |
| AGGREGATE_OWNERSHIP | Remove name gate; retain behavior tests | Project owns its locations — [PR154#4281754927](https://github.com/E5presso/neurath/pull/154#discussion_r4281754927) | Verify owned mapping and atomic persistence, not a repository name. |
| ALEMBIC_REVISION | Remove string gate; retain migration tests | Alembic owns schema revisions — [PR155#4321731311](https://github.com/E5presso/neurath/pull/155#discussion_r4321731311) | A real additional revision must work without parallel latest-head state; diagnostic strings are valid. |
| APPLICATION_BOUNDARY | Retain | Application and persistence responsibilities differ — [PR154#4280880042](https://github.com/E5presso/neurath/pull/154#discussion_r4280880042) | Check known storage/entrypoint dependency directions. |
| COLLECTION_CONTRACT | Remove universal tuple gate; scope contract tests | Read-only repository lists use Sequence — [PR155#4321715119](https://github.com/E5presso/neurath/pull/155#discussion_r4321715119),4321717283 | Check the two reviewed list ports; allow tuple types with other purposes. |
| CORE | Remove | The previous Core facade had no clear responsibility — [PR154#4280341976](https://github.com/E5presso/neurath/pull/154#discussion_r4280341976) | A class or module name does not establish that problem. |
| DATABASE_WRAPPER | Remove | The old database wrapper was unnecessary — [PR154#4280970066](https://github.com/E5presso/neurath/pull/154#discussion_r4280970066) | Do not universally prohibit the SqliteDatabase name. |
| DECLARATIVE_ORM | Narrow to registered models | Use Spakky declarative ORM — [PR154#4280368400](https://github.com/E5presso/neurath/pull/154#discussion_r4280368400) | Check actual Table registration bases, not all SQLAlchemy Table/Column expressions. |
| DEPENDENCY_COMPOSITION | Remove constructor-name gate; retain DI tests | Use framework dependency injection — [PR154 review 5530407770](https://github.com/E5presso/neurath/pull/154#pullrequestreview-5530407770); Current conversation Spakky 전환 | Verify actual injection and request cleanup instead of guessing from constructor names. |
| DOCSTRING | Remove duplicate AST gate; retain standard lint | Provide standard docstrings — [PR154#4280349254](https://github.com/E5presso/neurath/pull/154#discussion_r4280349254); review5530407770 | Keep shared Ruff and pydoclint checks. |
| DOMAIN_BOUNDARY | Remove library allowlist; retain dependency direction | Domain owns its policies — [PR154#4280880042](https://github.com/E5presso/neurath/pull/154#discussion_r4280880042),4280894714 | Reject known upward/storage dependencies, not arbitrary standard libraries. |
| ENTITY_IDENTITY | Remove id-name inference; retain identity tests | Distinguish entities and values — [PR154#4280930212](https://github.com/E5presso/neurath/pull/154#discussion_r4280930212) | An id field alone does not establish entity semantics. |
| ENTITY_MUTABILITY | Remove frozen/id inference; retain state tests | Entities were incorrectly treated as values — [PR154#4280930212](https://github.com/E5presso/neurath/pull/154#discussion_r4280930212) | An immutable value may legitimately contain an id. |
| EXPLICIT_IMPORT | Remove duplicate gate | Maintain standard code quality — [PR154 review 5529723813](https://github.com/E5presso/neurath/pull/154#pullrequestreview-5529723813) | Keep normal Ruff diagnostics without a second custom ban. |
| EXPLICIT_OBJECT_SELECTION | Remove | Prefer explicit type and responsibility relationships — [PR154#4280360643](https://github.com/E5presso/neurath/pull/154#discussion_r4280360643) | That comment did not prohibit every mapping.get(...) or expression. |
| FORBIDDEN_TYPE | Retain Protocol only | Explicit Protocol exclusion; Enum for domain states — [PR154#4280330548](https://github.com/E5presso/neurath/pull/154#discussion_r4280330548),4280345704 | Allow Any/cast/Literal in other roles; test the actual four Enum state types. |
| FRAMEWORK_CRUD | Remove universal override gate; retain current-contract tests | Reuse existing repository operations — Current conversation: Spakky 기본 기능 재사용 | Verify inherited methods and actual behavior of the current four repositories. |
| FRAMEWORK_REQUEST | Remove suffix inference; retain typing/input checks | Use framework use-case contracts — [PR155#4321719836](https://github.com/E5presso/neurath/pull/155#discussion_r4321719836) | Check actual registered-handler inputs and generic bounds. |
| FRAMEWORK_USECASE | Narrow to registered handlers | Inherit framework use-case interfaces — [PR155#4321719836](https://github.com/E5presso/neurath/pull/155#discussion_r4321719836) | Use actual UseCase metadata rather than a class-name suffix. |
| INFRASTRUCTURE_BOUNDARY | Retain | Keep layer responsibilities separate — Current conversation 및 PR154 책임 분리 리뷰 | Check the existing infrastructure-to-entrypoint dependency direction. |
| MAPPED_COLUMN | Remove all-attribute gate; retain mapping tests | Use typed declarative persistence — [PR154#4280360643](https://github.com/E5presso/neurath/pull/154#discussion_r4280360643),4280368400 | Do not treat every class attribute as a persistent column; compare real schema and metadata. |
| NOMINAL_IMPLEMENTATION | Narrow to repository registration | Make type ancestry explicit — [PR154#4280360643](https://github.com/E5presso/neurath/pull/154#discussion_r4280360643) | Check actual registration/contracts and DI, not Observer/Repository suffixes. |
| NOMINAL_PORT | Narrow to port declarations | Explicit nominal abstract contracts — [PR154#4280330548](https://github.com/E5presso/neurath/pull/154#discussion_r4280330548),4280360643 | Apply to I-capital interface declarations in port modules, not ordinary input DTOs. |
| OBSERVATION_BOUNDARY | Remove token ban; retain concrete observation tests | Adapters must not choose project identity policy — [PR154#4280894714](https://github.com/E5presso/neurath/pull/154#discussion_r4280894714) | Verify DirectoryObservation and Project identity/promotion/conflict behavior. |
| PRIMITIVE_REPOSITORY | Remove method/argument whitelist | Repositories query and persist — [PR154#4280880042](https://github.com/E5presso/neurath/pull/154#discussion_r4280880042),4280885303 | A query name or expected_revision parameter does not establish domain-policy ownership. |
| REPOSITORY_POLICY | Remove call-name blacklist | Keep domain rules with their owner — [PR154#4280880042](https://github.com/E5presso/neurath/pull/154#discussion_r4280880042) | Calling create/move alone does not establish an ownership violation. |
| REPOSITORY_SAVE | Remove name blacklist; retain save behavior | Unify insertion/update through save — [PR154#4281760345](https://github.com/E5presso/neurath/pull/154#discussion_r4281760345) | Verify the actual storage contract without banning unrelated helper factories. |
| RESULT_LOCATION | Remove path/name/mandatory-shape gates; retain current DTO cases | Colocate dedicated output DTOs with their use cases — Current conversation: result dto도 유즈케이스 안에 정의 | Test current dedicated DTOs without a global suffix, frozen, mandatory DTO, or fixed component count. |
| SELF_RETURN | Narrow to subtype-preserving construction | Use Self with the supported Python version — [PR154#4305379584](https://github.com/E5presso/neurath/pull/154#discussion_r4305379584),4305381892 | Check cls constructors; permit a factory that deliberately returns a fixed concrete type. |
| SUPPRESSION | Retain coverage exclusions only | 100% lines/branches without exclusions — Current conversation: 라인·분기 100%, 제외 처리로 숫자만 맞추지 말 것 | Keep zero excluded lines and coverage-pragma checks; remove blanket noqa/type-ignore bans. |
| TRANSACTION_WRAPPER | Remove names/syntax gates; retain lifecycle tests | Reuse ORM/framework transaction management — [PR154#4280335140](https://github.com/E5presso/neurath/pull/154#discussion_r4280335140); Current conversation Spakky 전환 | commit/rollback names or yield plus begin do not establish duplication. |
| TRANSPORT_PASSTHROUGH | Remove path blacklist | The previous transport relay had no real responsibility — [PR155#4321735899](https://github.com/E5presso/neurath/pull/155#discussion_r4321735899) | Review actual protocol/adaptation work without reserving or banning a filename forever. |
| USECASE_INTERFACE | Remove name blacklist | The fixed operation did not need a custom policy interface — [PR154#4280903353](https://github.com/E5presso/neurath/pull/154#discussion_r4280903353); [PR155#4321719836](https://github.com/E5presso/neurath/pull/155#discussion_r4321719836) | Reuse current framework contracts without globally banning IUseCase names. |

## Other audited surfaces

- AGENTS/CLAUDE: CLAUDE.md links to AGENTS.md. Remove unsupported name, path, function, and exception prohibitions; retain responsibility review.
- Ruff, strict Pyrefly and Google-style pydoclint: retain the established quality path. Do not add unsupported semantic bans on top of tool diagnostics.
- Korean documentation: remove character ratios and per-line quotas. The minimal check only reports actual docstrings without Korean prose outside code/formatting; translation and language appropriateness require review.
- Current repositories: preserve inherited default methods and actual insert/update through save, batch/delete/conflict tests. There is no universal override or helper-name ban.
- ORM/DI: check actual registered declarative Table bases and real registry, connection, session, transaction, isolation, and failure cleanup.
- Alembic: verify a real additional migration, compatibility lookup, explicit upgrade and retained records. Revision-looking strings are not forbidden.
- Coverage: retain the directly requested 100% of all product statements and branches, zero missing/excluded lines, and real report validation.
- Git hook and CI: share the quality entrypoint and retain previous-hook preservation, checkout isolation, and error propagation. Unknown hook folders/bare repositories are preservation or support limitations, not new business approval gates.
- Public specification: retain CLI-only distribution, rules entry, selected workflow phases, TODO-based termination, independent evaluation, requested retrospection, and original-data preservation. No human-input authentication, new consent ledger, or duplicate completion vote is added.
- Setup and retained host registrations: candidate setup remains unavailable because CLI/installer work is not implemented. Legacy local host registrations do not prove candidate installation or activation. No original DB, host identity, permissions, or installation is changed by this audit.

This report is evidence for this audit, not a new approval registry or rule-generation mechanism. Syntax checks do not establish semantic ownership, DDD correctness, or fulfillment of user intent. The corrected domain ownership implementation remains in place.

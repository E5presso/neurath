---
name: create-ticket
description: 승인된 plan, investigation result, follow-up work item에서 검증된 GitHub Issue를 생성합니다.
intent-class: ticket.create
input-authority: repository-spec
not-for: [spec.plan, ticket.execute]
argument-hint: "<plan path, investigation result, or work item> [--parent #N] [--milestone title]"
user-invocable: true
---

# Create Ticket

Neurath의 단일 GitHub Issue 생성 boundary입니다. planning과 investigation skill은
work가 필요하다고 결정할 수 있지만, GitHub mutation, template choice, metadata
policy, read-back verification은 이 skill이 소유합니다.

GitHub Issues가 유일한 tracker입니다. 다른 tracker issue를 만들거나 참조하지
않습니다.

## 결정적 phase 실행

Operational phase는 `uv run python -m scripts.skill_harness.phase_runner` 실행 결과를 잇습니다.
`current`는 recovery 전용이고 마지막 `complete --terminal-state`가 terminal CAS를 닫습니다.

## Tool runtime 호환성

`.agents/rules/tool-runtime-map.md`를 사용합니다. `tool:github`, `tool:run_shell`,
`tool:read_file`, `tool:search_files`, `tool:ask_user`, `tool:phase_runner` 같은
tool action은 Claude Code와 Codex에서 이 map을 통해 변환합니다.

## GitHub Metadata 언어

GitHub metadata는 대상 프로젝트가 정한 언어와 형식으로 작성합니다.
제목·본문·commit subject의 형식과 issue 연결 규칙은 저장소 템플릿을 확인합니다.
`github_metadata_language` validator는 `.neurath/project.json`의 metadata 설정을
읽습니다. 게시 전후 실제 read-back을 검사하고 `policy_passed=true`를 확인합니다.
한국어 또는 issue prefix는 해당 프로젝트가 명시적으로 설정했을 때만 요구합니다.


## 전제조건

GitHub을 변경하기 전에 다음을 확인합니다.

- GitHub remote 또는 explicit repository target이 있습니다.
- `gh auth status`가 성공하거나 GitHub connector를 사용할 수 있습니다.
- source plan, investigation result, follow-up request가 title, intent, scope,
  acceptance criteria를 쓸 만큼 명확합니다.
- follow-up request에는 `.agents/rules/behavioral.md`의 Gap Triage decision이
  있습니다. 현재 work item에서 처리해야 하는 gap, 스펙이 불명확한 gap, 가치가
  낮거나 중복인 gap은 GitHub Issue로 만들지 않습니다.
- 작업 유형이 대상 프로젝트에서 허용되며 목적과 종료 기준이 명확합니다.
  구현 작업은 승인된 요구사항과 검증 기준, 조사 작업은 질문과 근거·산출물 기준을 갖춥니다.
- implementation issue는 한 agent, 한 session에서 context rot 없이 완료 가능한
  크기입니다. Capability parent 또는 milestone급 work가 implementation child로
  들어오면 생성하지 않고 `/plan-issues` 분해로 되돌립니다.
- 다티켓 hierarchy는 `task_size_audit`, `write_conflict_matrix`,
  `dependency_graph`, `critical_path`, `parallel_groups`,
  `blocked-by metadata`를 가집니다. 모든 child가 병렬이면
  `all_parallel_approval` 근거가 있어야 합니다.
- 요청이 GitHub Issue 생성을 명시하지 않았다면 사용자가 external GitHub Issue
  creation을 승인했습니다.
- parent, milestone, labels, assignee, blocked-by input이 알려져 있거나 문서화된
  fallback이 있습니다.

전제조건이 빠지면 run을 `blocked`로 finalize합니다. partial local plan을 만들고
ticket이라고 보고하지 않습니다.

## Phase 개요

| Phase | 목적 |
|-------|------|
| 1 | issue content와 metadata 준비 |
| 2 | GitHub object 생성 또는 갱신 |
| 3 | GitHub read-back 검증 |
| 4 | 생성된 ticket 보고 |

## Template 선택

source of truth에서 body template을 선택합니다.

- planned behavior, capability, product work, harness work, DevOps work,
  `/plan-issues` decomposition에는 `.github/ISSUE_TEMPLATE/feature.yml`을 사용합니다.
- reproduced defect, failing check, `/investigate`의 confirmed regression에는
  `.github/ISSUE_TEMPLATE/bug.yml`을 사용합니다.
- 승인된 spec에서 hierarchy를 만들 때는
  `.agents/skills/plan-issues/templates.md`의 parent/child issue body shape를
  사용합니다.

모든 issue body에는 `## 실행 소유권` section을 포함합니다. 이 section은
수행자가 agent이며, 사용자는 스펙 검토자와 최종 산출물 검수자이고, agent가
research, planning, implementation, verification, GitHub metadata, docs sync를
직접 수행한다는 점을 명시해야 합니다. Ticket body가 사용자에게 실행 작업을
배정하는 표현을 포함하면 생성 또는 갱신 전에 고칩니다.

모든 issue body에는 `## Clean-slate 맥락` section도 포함합니다. 이 section은
새 agent가 chat history 없이 읽어야 하는 source of truth, 확정 결정, 비목표,
열린 blocking decision, 검증 기준을 알려야 합니다. Issue가 인간 수준의 암묵
맥락 이해에 의존하거나 agent가 빈칸을 추측해야 한다면 생성하지 않습니다. 반대로
확정되지 않은 추측, 중복 narrative, 오래된 세부사항을 넣어 context rot을 만들지
않습니다.

Issue 본문 형식은 대상 프로젝트 템플릿을 따릅니다. 구현·조사 등 작업 유형을
명확히 밝히고 승인된 범위, 필요한 결정, 검증 방법과 완료 조건을 포함합니다.

대상 프로젝트에 용어집이나 명명 규칙이 있으면 이를 연결하고 새 용어·충돌을
기록합니다. 특정 문서 경로나 클래스·메서드 명명 형식을 하네스가 강제하지 않습니다.

모든 implementation child issue body에는 `## Task Size Audit` section을
포함합니다. 이 section은 예상 변경 파일 수, 예상 코드 변경량, 관여 package/app/
service, acceptance criteria 수, 한 agent/session 완료 가능 판정을 명시해야
합니다. 이 판정이 없거나 parent급 work를 child로 위장하면 issue를 생성하지
않습니다.

follow-up issue body에는 `## Gap Triage` section을 포함합니다. 이 section은
현재 작업에서 즉시 처리하지 않는 이유, 독립 work item인 이유, priority,
acceptance, owner/agent route, 재개 조건, source evidence를 명시해야 합니다.
이 section이 비어 있거나 "나중에 처리"만 말하면 issue를 생성하지 않습니다.

모든 issue body는 temporary Markdown file로 작성하고 `--body-file`로 issue를
생성합니다. 긴 body text를 shell inline으로 넘기지 않습니다.

## Metadata policy

labels, assignee, milestone, parent link, blocked-by edge는 ticket contract의
일부입니다.

- `labels`: 선택한 GitHub issue template, source issue, 승인된 plan, explicit user
  request에서 label을 적용합니다. required label이 없으면 repository convention이
  이미 승인된 경우에만 만들고, 아니면 ticket을 blocked로 두고 missing label을
  보고합니다.
- `assignee`: explicit assignee를 우선합니다. 기존 issue의 follow-up이면 plan이
  다르게 말하지 않는 한 source issue assignee를 복사합니다. assignee가 없으면
  `assignee_policy`에 `unassigned-agent-owned` 같은 문서화된 fallback과 사유를
  기록합니다. Plan-driven hierarchy에서 fallback 근거 없이 assignee를 비워 두면
  blocked입니다.
- `milestone`: plan-driven hierarchy에는 요청된 milestone을 create 또는 reuse합니다.
  active scope 안의 follow-up이면 source milestone을 복사합니다. milestone이
  없으면 standalone investigation ticket에만 비워두고 omission을 보고합니다.
- `parent`: hierarchy에 속한 child issue는 requested parent issue에 연결합니다.
- `blocked-by`: dependency edge는 GitHub-native metadata로 encode합니다. Markdown
  "Blocked by" line은 context일 뿐 metadata 대체물이 아닙니다.
  GraphQL을 사용할 때는 `addBlockedBy` mutation을 사용하고, read-back에서
  `blockedBy.totalCount`와 blocker issue 번호를 확인합니다. body나 comment는 blocked-by metadata를 대체하지 못합니다.
- `project/status`: repository가 GitHub Project를 사용하는 scope이면 source issue,
  milestone, plan의 project/status를 상속하거나 documented omission을 남깁니다.

## 생성 절차

1. source artifact는 `tool:read_file`로, GitHub issue data는 `tool:github`으로
   읽습니다.
2. issue type, title, body file, labels, assignee, milestone, parent,
   blocked-by edge를 도출합니다.
3. implementation child마다 `task_size_audit`와 `parallelization_plan`을
   확인합니다.
4. phase 1을 `content_plan`, `body_files`, `label_plan`, `assignee_plan`,
   `relationship_plan`, `task_size_audit`, `parallelization_plan` evidence로
   완료합니다.
5. 필요하면 milestone을 create 또는 reuse합니다.
6. child issue보다 parent issue를 먼저 만듭니다.
7. child 또는 standalone issue는 `gh issue create --body-file` 또는 GitHub
   connector로 만듭니다.
8. creation command가 설정하지 못한 parent/sub-issue와 `blocked-by` metadata는
   생성 후 GitHub-native field 또는 equivalent API로 적용합니다.
9. phase 2를 `created_issue_urls`, `milestone_result`,
   `metadata_mutation_result` evidence로 완료합니다.

`gh` command에는 `tool:run_shell`, connector call에는 `tool:github`을 사용합니다.

## 검증

성공을 보고하기 전에 모든 created issue를 다시 읽습니다. 다음을 검증합니다.

- issue URL과 number
- title과 body
- labels
- assignee
- milestone
- project/status metadata 또는 documented omission
- parent/sub-issue relationship
- blocked-by metadata
- `blocked_by_metadata`: GitHub-native `blockedBy.totalCount`와 blocker issue 번호
  read-back. blocker가 없는 issue라면 `blocked_by_metadata=none expected=true`처럼
  의도된 무의존 상태임을 명시합니다.
- child issue dependency graph
- `## Task Size Audit` section과 한 agent/session 완료 가능 판정
- `critical_path`, `parallel_groups`, `write_conflict_matrix`,
  `all_parallel_approval` read-back
- `## 실행 소유권` section과 agent-owned execution 문구
- `## Clean-slate 맥락` section과 source of truth, non-goal, blocking decision,
  context rot 회피 문구
- `## Domain Dictionary Lookup` section과 DD source, 새 용어 또는 충돌 표현,
  class/method naming source
- follow-up issue라면 `## Gap Triage` section과 priority, acceptance,
  owner/agent route, 재개 조건, source evidence

`readback_issues`, `readback_metadata`, `verification_result` evidence가 요청된
ticket plan과 모두 일치한 뒤에만 phase 3을 완료합니다.

## 최종 보고

다음을 보고합니다.

- created issue number와 URL
- milestone URL 또는 number
- parent issue number
- issue별 labels와 assignee
- blocked-by edge list
- 사용한 verification command 또는 API read
- unresolved blocker

GitHub read-back이 ticket metadata를 확인한 뒤에만 `created`로 finalize합니다.
approval 없음, GitHub auth 없음, repository 불명, missing labels, unresolved
ownership/milestone decision은 `blocked`를 사용합니다. 정상 동작해야 했던 GitHub
mutation 또는 verification error는 `failed`를 사용합니다.

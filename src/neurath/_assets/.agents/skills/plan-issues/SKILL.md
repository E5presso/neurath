---
name: plan-issues
description: 새 Neurath product intent와 product·domain·architecture decision을 질문(grilling)으로 명확히 하고, 확정 결과를 durable 문서와 GitHub Issue hierarchy로 분해합니다. 기존 spec audit, 승인된 single work item 실행, private-memory pattern 승격에는 사용하지 않습니다.
intent-class: spec.plan
input-authority: user-product-intent
not-for: [ticket.create, ticket.execute]
argument-hint: "<제품 방향, 기능 아이디어, 문제 설명>"
user-invocable: true
---

# Plan Issues

사용자가 대상 프로젝트의 목적, 기능 모양, 문제 정의, 구현 단위 분해를 논의하려고
할 때 사용합니다.

이 스킬은 구현 스킬이 아닙니다. 먼저 제품 의도와 스펙을 닫고, 문서로
보존한 뒤, GitHub Issue 계층을 정의합니다. GitHub 객체 생성은
`/create-ticket`에 위임합니다. `/plan-issues`는 계획, 문서화, Issue 계층
의도를 소유하고, `/create-ticket`은 템플릿, 라벨, 담당자, milestone,
parent link, `blocked-by` metadata 생성을 소유합니다.

계획을 시작하기 전에 canonical planning posture인
`references/planning-posture.md`를 전부 읽습니다.

## 결정적 phase 실행

계약이 있는 phase 작업은 반드시 다음 명령으로 초기화, 조회, 완료, 평가,
종료합니다.

```bash
uv run python -m scripts.skill_harness.phase_runner
```

phase runner가 evidence를 수락하고 다음 phase 또는 종료 출력을 내기 전에는
phase 완료, 다음 phase 진입, 최종 결과를 주장하지 않습니다.

## 도구 runtime 호환성

`.agents/rules/tool-runtime-map.md`를 사용합니다. phase 파일은 도구 행동을
`tool:<key>`로 표현할 수 있으며, Claude Code와 Codex에서는 이 map을 통해
실제 도구 호출로 변환합니다.

## 핵심 계약

계획은 구현이 아닙니다. 최종 산출물은 `/process-ticket`이 추측 없이 구현할
수 있을 만큼 명확해야 합니다.

작업 유형과 개발 절차는 대상 프로젝트 지침과 현재 요청을 따릅니다. 구현 ticket에는
승인된 요구사항과 실행 가능한 검증 기준을 연결합니다. 조사나 비교 작업은 질문,
근거 범위, 산출물과 종료 기준을 명시하고 구현 완료와 구분합니다.

GitHub Issue는 clean-slate agent instruction입니다. 새 agent가 대화 기록 없이
ticket과 연결된 repository docs만 읽어도 제품 의도, 범위, 비목표, 선행 문서,
test-first 시작점, dependency, 실행 소유권을 이해할 수 있어야 합니다. Agent가
고도의 인간적 맥락 추론으로 빈칸을 채워야 하는 ticket은 잘못 작성된 ticket이며,
phase 5에서 통과시키지 않습니다. 반대로 확정되지 않은 추측과 오래된 세부사항을
과도하게 붙여 context rot을 만들지 않습니다.

## Issue 크기와 병렬화 계약

`/plan-issues`는 GitHub Issue를 만들기 전에 capability parent와 implementation
child를 구분합니다. 부모 issue는 단일 제품 가치나 단일 관심사 묶음을 설명하고,
실제 `/process-ticket`이 소비하는 구현 issue는 한 agent, 한 세션에서 context rot
없이 끝낼 수 있는 크기여야 합니다.

위계는 다음 기준을 따릅니다.

| 위계 | 의미 | GitHub 대응 |
|------|------|-------------|
| Milestone | 새 제품 가치 또는 복수 관심사 묶음 | GitHub Milestone |
| Capability Parent | 단일 관심사, 2-5개 구현 issue 묶음 | Parent issue |
| Implementation Child | 단일 agent/session, 단일 PR로 완료할 작업 | Child issue |

Implementation Child의 기본 상한은 다음과 같습니다. 정성 기준이 우선하지만, 초과
시 `task_size_audit`에 이유를 남기고 더 작은 child issue로 분해합니다.

- 예상 변경 파일 수: 5개 이하.
- 예상 코드 변경량: 신규 300줄 또는 수정 200줄 이하.
- 관여 package/app/service 수: 1개. Cross-cutting work는 선행 contract issue와
  각 package별 child issue로 분해합니다.
- Acceptance Criteria: 3-5개.

분해 결과에는 `write_conflict_matrix`, `dependency_graph`, `critical_path`,
`parallel_groups`, `blocked_by_metadata`가 있어야 합니다. 여러 child issue가 전부
병렬이라고 판단되면 `all_parallel_approval`에 사용자 승인 또는 코드/문서 근거를
명시합니다. 승인이나 근거 없이 다티켓 분해의 모든 `blocked_by`가 비어 있으면
Critical 실패로 보고하고 phase 2 또는 4로 돌아갑니다.

병렬화를 위해 contract, interface, generated client, shared schema, migration처럼
다른 issue가 의존하는 work는 선행 child issue로 둡니다. 반복 패턴을 여러 영역에
적용할 때는 첫 child를 reference implementation으로 지정하고 나머지 issue는 그
결과에 의존하거나 참조 관계를 명시합니다.

Grilling은 사용자에게 모든 세부사항을 묻는 절차가 아닙니다. 이미 닫힌
결정과 repository 문서에서 높은 confidence로 도출할 수 있는 세부사항은 agent가
자율 판단하고, `decision_log`와 `.neurath/project.json (documents 슬롯)`에 근거와 함께
기록합니다. 사용자에게 묻는 질문은 제품 의미, 권한 경계, privacy/safety
trade-off, 되돌리기 어려운 architecture decision처럼 agent가 추론으로 닫으면
위험한 decision-shaping branch로 제한합니다.

질문 routing은 `.agents/rules/evaluation-loops.md`의 adaptive control을 사용합니다. Ambiguity
score는 질문 우선순위일 뿐 closure 권한이 아니며, user-owned material blocker 하나를 평균값으로
숨길 수 없습니다. Repository/source authority인 gap은 먼저 조사하고, 질문은 current 결과를 바꾸는
가장 upstream user gap 하나만 선택합니다.

Phase 0에서는 closed `RequirementSection` 전체를 평가한 canonical state를
`state_cli adaptive replace`로 exact workflow revision에 기록합니다. 일부 section만 평가한 빈 gap
목록은 initialized evidence가 아니며, raw workflow payload 수정은 금지합니다. 이후 답변이나 source
read-back으로 intent/source revision이 바뀔 때마다 같은 typed state를 CAS 갱신합니다. Phase runner가
첫 phase의 `adaptive_control_initialized`와 마지막 phase의 완료 결과를 공통으로 강제하므로
skill 내부에 별도 우회 branch를 만들지 않습니다.

Phase 2의 반복 순서는 항상 `질문 -> 사용자 답변 해석 -> 높은 confidence
자율 파생 결정 계산 -> repository ledger/DD/spec artifact 저장 -> 다음 질문`입니다.
자율 판단한 세부사항을 저장하지 않은 채 다음 질문으로 넘어가지 않습니다. 저장
대상은 최소한 `decision_log`이며, compaction 뒤에도 필요하면
`.neurath/project.json (documents 슬롯)`와 `.neurath/project.json (documents 슬롯)`에 즉시 보존합니다.

질문 granularity는 사용자에게 묻기 전에 gate합니다. 질문 후보가 이미 승인된
domain boundary, 권한 hierarchy, privacy default, role responsibility에서
자연스럽게 따라오는 하위 lifecycle, default state, reviewer/approver, 단순
allow/deny라면 묻지 않습니다. 반대로 답에 따라 제품 경험, 신뢰 모델,
permission boundary, data ownership, safety posture, 또는 milestone/work item
경계가 달라지면 질문합니다.

예를 들어 어떤 대상에 권한 제어를 두지 않기로 이미 확정했다면, 그 대상의
하위 role과 default allow/deny를 다시 묻지 않고 확정 결정에서 파생해 저장합니다.
반대로 그 대상을 어떤 단위로 식별하고 얼마나 오래 보존할지는 제품 경험과 data
retention 경계가 달라지므로 질문합니다.

확정 결정에서 기계적으로 따라오는 lifecycle 결과는 질문으로 올리지 말고 근거와
함께 ledger와 DD에 저장합니다.

## 참고한 planning posture

Matt Pocock의 `grill-with-docs`는 집요한 질문 흐름과 `domain-modeling`을
결합합니다. Neurath에서는 이 태도를 phase 2에 적용합니다. 즉, 질문으로
스펙을 날카롭게 만들고, 문서와 코드의 언어를 대조하며, 결정 ledger를
유지합니다.

참고 지점은 2026-06-21에 확인했습니다.

- `https://github.com/mattpocock/skills/blob/main/skills/engineering/grill-with-docs/SKILL.md`
- `https://github.com/mattpocock/skills/blob/main/skills/engineering/domain-modeling/SKILL.md`
- `https://www.aihero.dev/grill-with-docs`
- `https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/adding-sub-issues`
- `https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/creating-issue-dependencies`
- `https://cli.github.com/manual/gh_issue_create`

## 맥락 window 회복성

planning 결정은 compaction, thread reset, phase handoff 뒤에도 살아남아야
합니다. 대화가 길어지면 다음 질문으로 넘어가기 전에
`.neurath/project.json (documents 슬롯)`를 갱신합니다.

phase 2 완료 evidence에는 `decision_log`와 `compaction_resume_source`가
필수입니다. phase 4 완료 evidence에는 `product_context`와 `decision_log`가
필수입니다.

## Phase 개요

각 phase에 진입할 때 해당 phase 파일을 읽습니다.

| Phase | 목적 | 파일 |
|-------|------|------|
| 0 | 입력 수집 | `phases/phase-0-input.md` |
| 1 | 문서와 코드 분석 | `phases/phase-1-analysis.md` |
| 2 | grilling과 계획 | `phases/phase-2-plan.md` |
| 3 | 스펙 artifact 고정 | `phases/phase-2_5-spec.md` |
| 4 | 문서 보존 | `phases/phase-3-document.md` |
| 5 | cold-read 실행 시뮬레이션 | `phases/phase-3_5-simulate.md` |
| 6 | GitHub Issue 계층 생성 | `phases/phase-4-create.md` |
| 7 | 결과 보고 | `phases/phase-5-report.md` |

## 필수 ledger

전체 흐름 동안 다음 ledger를 유지합니다.

- `decision_tree`: 열린 질문과 답변에 따라 활성화되는 branch.
- `decision_log`: 확정 결정, 보류 결정, 기각된 해석, 근거, 출처.
- `compaction_resume_source`: 이후 agent가 대화 기록 없이 다시 읽어야 할
  repository 파일.
- `language_ledger`: DD lookup 결과, 확정, 모호, 충돌, 과적재된 용어.
- `domain_dictionary_delta`: 새 DD 용어, 의미, 피할 표현, 출처.
- `product_context`: durable product intent를 대표하는 context 파일.
- `doc_updates`: context와 glossary 변경 사항.
- `adr_candidates`: ADR이 필요할 수 있는 결정.
- `work_items`: 구현 단위와 의존성.
- `task_size_audit`: 각 implementation child가 한 agent/session 단위인지 검토한
  결과와 초과 시 분해 근거.
- `write_conflict_matrix`: 병렬 issue 간 같은 file/module/service 충돌 가능성.
- `critical_path`: milestone 또는 parent issue 완료까지의 필수 선행 경로.
- `parallel_groups`: 동시에 `/process-ticket`로 실행 가능한 issue 그룹.
- `all_parallel_approval`: 다티켓 분해에서 모든 `blocked_by`가 비어 있을 때의
  명시 승인 또는 근거.
- `fr_sc_coverage`: 모든 FR/SC가 최소 1개 implementation child에 매핑되는지
  확인한 coverage table. durable 산출물은 `.neurath/project.json (documents 슬롯)`이며,
  생성되는 순간부터 spec harness가 전 FR 커버리지와 서비스 귀속을 기계 검사합니다.
- `test_plan`: production code보다 먼저 작성할 failing 또는
  characterizing test.
- `github_issue_hierarchy`: milestone, parent issue, child issue,
  `blocked_by_metadata` edge.
- `adaptive_control`: current goal fingerprint, clarification gaps와 authority, criterion evidence,
  independent coverage, reflection action을 가진 workflow-local latest state.

해결되지 않은 ledger item을 최종 prose 안에 숨기지 않습니다. 해결하거나,
문서로 보존하거나, 계획을 blocked 상태로 종료합니다.

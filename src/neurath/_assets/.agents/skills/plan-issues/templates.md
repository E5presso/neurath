# Plan Template

## 스펙 artifact

```markdown
# {계획 제목}

## 1. 제품 의도

{누가 이득을 보고, 무엇이 바뀌며, 왜 지금 필요한가.}

## 2. 가정

- {가정}

## 3. 시나리오

### 시나리오: {이름}

Given {상태}, when {행동}, then {관찰 가능한 결과}.

## 4. 요구사항

- FR-001: {검증 가능한 단일 문장}.

## 5. 계약

- 입력: {의미와 제약}
- 출력: {의미와 상태}
- 소유권: {Neurath가 소유하는 것 또는 읽기만 하는 것}

## 6. 비목표

- {명시적 제외}

## 7. 성공 기준

- SC-001: {관찰 지점, 목표, 기대값}

## 7.1 FR/SC Coverage

| ID | 의미 | 담당 work item |
|----|------|----------------|
| FR-001 | {요구사항} | {Work item ID} |
| SC-001 | {성공 기준} | {Work item ID} |

## 8. Domain Dictionary Lookup

- 읽은 DD: `.neurath/project.json (documents 슬롯)`
- 대조한 context: `.neurath/project.json (documents 슬롯)`, `.neurath/project.json (documents 슬롯)`
- 용어 충돌: {없음 또는 충돌 목록}
- 코드/문서에서 확인한 기존 식별자: {class, method, package, API 이름}

## 9. Domain Dictionary Delta

| 용어 | 의미 | 피할 표현 | 출처 |
|------|------|-----------|------|

## 10. ADR 후보

| 결정 | ADR 후보인 이유 | 상태 |
|------|-----------------|------|

## 11. 결정 Log

| 결정 | 상태 | 근거 | 출처 |
|------|------|------|------|

## 12. Resume source

- `.neurath/project.json (documents 슬롯)`
- `.neurath/project.json (documents 슬롯)`

## 13. 실행 소유권

- 수행자: agent.
- 사용자 역할: 스펙 검토자와 최종 산출물 검수자.
- Agent는 승인된 context를 읽고 상세 스펙, 조사, test-first plan, issue hierarchy,
  implementation plan을 먼저 작성합니다.
- 사용자에게는 blocking product decision 또는 final acceptance만 요청합니다.
- 이 artifact는 사용자에게 research, planning, implementation, verification,
  GitHub metadata, documentation 작업을 맡기지 않습니다.
- 작업 유형과 절차는 대상 프로젝트가 결정합니다. 구현은 요구사항과 검증 기준,
  조사는 질문·근거·산출물·종료 기준을 명시합니다.

## 14. Clean-slate 맥락

- 새 agent가 chat history 없이 이 문서와 연결된 repository docs만 읽어도 실행
  방향을 이해할 수 있어야 합니다.
- 필요한 context source, 확정 결정, 비목표, acceptance, 검증 명령을 명시합니다.
- 확정되지 않은 추측, 중복 narrative, 오래된 세부사항은 넣지 않습니다.
```

## 문서화 ledger

```markdown
# 문서화 Ledger

## 스펙

- 경로: `.neurath/project.json (documents 슬롯)`
- 승인 출처: {chat, issue, plan review}

## 맥락 업데이트

- `.neurath/project.json (documents 슬롯)`: {변경}

## 결정 Log

- `.neurath/project.json (documents 슬롯)`: {확정, 보류, 기각 결정 기록}

## Domain Dictionary Delta

| 용어 | 의미 | 피할 표현 | 출처 |
|------|------|-----------|------|

## ADR 결정

| 결정 | 조치 | 이유 |
|------|------|------|

## 막힌 문서화

- {Issue 생성 전에 문서화를 완료할 수 없을 때만 작성}
```

## Work Item

```markdown
# {Work Item 제목}

## 의도

{이 항목이 승인된 스펙 안에 존재하는 이유.}

## 작업 유형과 완료 기준

- 작업 유형은 대상 프로젝트에서 허용하는 구현·조사·운영 중 해당 항목을 명시합니다.
- 스펙 논의와 구체화는 ticket 발행 전에 완료됐습니다.
- Agent는 승인된 스펙을 기반으로 test-first 구현, 검증, 문서 동기화를 수행합니다.
- Agent가 제품 스펙을 새로 정해야 하면 ticket을 실행하지 않고 planning으로
  되돌립니다.

## 실행 소유권

- 수행자: agent.
- 사용자 역할: 스펙 검토자와 최종 산출물 검수자.
- Agent는 먼저 기존 context, 관련 issue, code, test, docs를 읽고 초안과 변경을
  작성합니다.
- 사용자에게는 blocking product decision 또는 final acceptance만 요청합니다.
- 이 ticket은 사용자에게 research, planning, implementation, verification,
  GitHub metadata, documentation 작업을 맡기지 않습니다.

## Clean-slate 맥락

- 먼저 읽을 문서: `{docs/context/...}`, `{docs/plans/...}`, `{ADR 또는 없음}`.
- 새 agent가 chat history 없이 이 ticket만 읽어도 범위와 비목표를 구분할 수
  있어야 합니다.
- 구현 agent가 추측하면 안 되는 열린 질문은 blocking decision으로 표시합니다.
- 오래된 세부사항이나 중복 narrative로 context rot을 만들지 않습니다.

## Domain Dictionary Lookup

- 먼저 읽을 DD: `.neurath/project.json (documents 슬롯)`
- 새 용어: {없음 또는 용어 목록}
- 충돌하는 표현: {없음 또는 표현 목록}
- 구현 시 따라야 하는 class/method naming: `.agents/rules/domain-dictionary.md`

## Domain Dictionary Delta

- {없음 또는 새 DD entry 목록}

## 범위

- {범위 안}

## Acceptance Criteria

- Given {상태}, when {행동}, then {관찰 가능한 결과}.

## FR/SC Trace

- 담당 FR: {FR-001, ...}
- 기여 SC: {SC-001, ...}

## Task Size Audit

- 예상 변경 파일 수: {N}개.
- 예상 코드 변경량: 신규 {N}줄 / 수정 {N}줄.
- 관여 package/app/service: {목록}.
- Acceptance Criteria 수: {N}개.
- 판정: {한 agent/session에서 context rot 없이 완료 가능 | parent issue로 분해 필요}.

## 검증

- 먼저 작성 또는 수정: `{failing 또는 characterizing test path}`.
- `uv run python -m scripts.agent_harness.verification_runner pytest --node {exact public pytest node}`
- `.neurath/run verify typecheck`

## 선행 이슈

- {없음 또는 `- [ ] #N {제목}`}

## Dependency Metadata

- GitHub-native `blockedBy` metadata must match `## 선행 이슈`.
- Blocked by: {issue numbers 또는 없음}
- Blocking: {issue numbers 또는 없음}
```

## Parent Issue 본문

```markdown
# {Milestone 제목}

## 스펙

- 계획: `.neurath/project.json (documents 슬롯)`

## 의도

{승인된 스펙의 제품 또는 운영 의도.}

## 실행 소유권

- 수행자: agent.
- 사용자 역할: milestone 스펙 검토자와 최종 산출물 검수자.
- Agent는 하위 issue 실행, 상세 스펙 작성, issue decomposition, dependency
  metadata, 검증, 문서 동기화를 직접 수행합니다.
- 사용자에게는 blocking product decision 또는 final acceptance만 요청합니다.
- 이 parent issue는 사용자에게 실행 작업을 배정하지 않습니다.
- Parent와 child에는 각각 작업 유형과 승인된 범위, 그에 맞는 완료 기준을 명시합니다.

## Clean-slate 맥락

- 먼저 읽을 문서: `.neurath/project.json (documents 슬롯)`,
  `.neurath/project.json (documents 슬롯)`, `.neurath/project.json (documents 슬롯)`.
- 이 parent issue는 새 agent가 milestone intent, child issue boundary,
  dependency direction을 chat history 없이 이해할 수 있게 작성합니다.
- 상세 구현이 아직 정해지지 않은 부분은 추측하지 않고 child issue 또는 blocking
  decision으로 분리합니다.
- 오래된 세부사항이나 중복 narrative로 context rot을 만들지 않습니다.

## 범위

- {포함 행동}

## 비목표

- {제외 행동}

## Child Issues

- [ ] {Child issue 제목}

## Task Size & Parallelization

| Child | Size 판정 | Write conflict | Parallel group |
|-------|-----------|----------------|----------------|

## Dependency Graph

- {Child A} -> {Child B}

## Critical Path

- {Child A} -> {Child B}

## Parallel Groups

- Group 1: {Child IDs}

## All Parallel Approval

- {해당 없음 또는 모든 child가 병렬이어도 되는 명시 승인/근거}

## 문서

- 맥락 문서 업데이트: {paths 또는 없음}
- Glossary 업데이트: {paths 또는 없음}
- ADR: {paths 또는 없음}
```

## Child Issue 본문

```markdown
# {Child Issue 제목}

## 스펙

- Parent plan: `.neurath/project.json (documents 슬롯)`
- Parent issue: #{parent-issue-number}

## 의도

{이 issue가 승인된 스펙 안에 존재하는 이유.}

## 작업 유형과 완료 기준

- 작업 유형과 그에 맞는 검증·산출물 기준을 명시합니다.
- 스펙 논의와 구체화는 ticket 발행 전에 완료됐습니다.
- Agent는 승인된 스펙을 기반으로 test-first 구현, 검증, 문서 동기화를 수행합니다.
- Agent가 제품 스펙을 새로 정해야 하면 ticket을 실행하지 않고 planning으로
  되돌립니다.

## 실행 소유권

- 수행자: agent.
- 사용자 역할: 상세 스펙 검토자와 최종 산출물 검수자.
- Agent는 기존 context를 바탕으로 상세 스펙, ADR 후보, work item, test-first
  plan, 하위 issue hierarchy 초안을 먼저 작성합니다.
- 사용자에게는 blocking product decision 또는 final acceptance만 요청합니다.
- 이 issue는 사용자에게 추가 장시간 grilling, research, planning,
  implementation, verification, GitHub metadata 작업을 맡기지 않습니다.

## Clean-slate 맥락

- 먼저 읽을 문서: `.neurath/project.json (documents 슬롯)`,
  `.neurath/project.json (documents 슬롯)`, `.neurath/project.json (documents 슬롯)`.
- 새 agent는 이 issue를 바탕으로 상세 스펙과 하위 work item 초안을 작성해야
  합니다.
- 구현 agent가 채우면 위험한 빈칸은 blocking product decision으로 표시합니다.
- 오래된 세부사항이나 중복 narrative로 context rot을 만들지 않습니다.

## Domain Dictionary Lookup

- 먼저 읽을 DD: `.neurath/project.json (documents 슬롯)`
- 새 용어: {없음 또는 용어 목록}
- 충돌하는 표현: {없음 또는 표현 목록}
- 구현 시 따라야 하는 class/method naming: `.agents/rules/domain-dictionary.md`

## Domain Dictionary Delta

- {없음 또는 새 DD entry 목록}

## 범위

- {범위 안}

## Acceptance Criteria

- Given {상태}, when {행동}, then {관찰 가능한 결과}.

## FR/SC Trace

- 담당 FR: {FR-001, ...}
- 기여 SC: {SC-001, ...}

## Test-First Plan

- 먼저 작성 또는 수정: `{failing 또는 characterizing test path}`.

## Task Size Audit

- 예상 변경 파일 수: {N}개.
- 예상 코드 변경량: 신규 {N}줄 / 수정 {N}줄.
- 관여 package/app/service: {목록}.
- Acceptance Criteria 수: {N}개.
- 판정: {한 agent/session에서 context rot 없이 완료 가능}.

## 검증

- `uv run python -m scripts.agent_harness.verification_runner pytest --node {exact public pytest node}`
- `.neurath/run verify typecheck`
- `uv run python -m scripts.agent_harness.verification_runner pre-commit`

## 선행 이슈

- 선행 이슈:
  - {없음 또는 `- [ ] #N`}

## Dependency Metadata

- GitHub-native `blockedBy` metadata must match `## 선행 이슈`.
- Blocked by: {issue numbers 또는 없음}
- Blocking: {issue numbers 또는 없음}
```

## GitHub Issue 계층

```markdown
# GitHub Issue 계층

## Milestone

- 제목: {milestone 제목}
- 설명: {승인된 스펙 요약}

## Parent Issue

- 제목: {parent issue 제목}
- Body file: {parent-body.md}

## Child Issues

| 임시 ID | 제목 | Body file | Size 판정 | Blocked by | Parallel group |
|---------|------|-----------|-----------|------------|----------------|

## Dependency Edges

- {blocked child temporary ID} blocked by {blocking temporary ID}

## Critical Path

- {temporary ID} -> {temporary ID}

## Parallel Groups

- Group 1: {temporary IDs}

## Write Conflict Matrix

| Work item | 예상 변경 경로 | 충돌 가능 issue | 판정 |
|-----------|----------------|-----------------|------|

## All Parallel Approval

- {해당 없음 또는 승인/근거}

## 검증

- Milestone: {created 또는 reused}
- Parent issue: #{number}
- Child issues: #{numbers}
- Blocked-by metadata: {verified edge list}
- Labels: {verified labels}
- Assignee: {verified assignee 또는 documented unassigned-agent-owned policy}
- Project/Milestone: {verified metadata}
```

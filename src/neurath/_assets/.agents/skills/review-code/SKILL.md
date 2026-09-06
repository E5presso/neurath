---
name: review-code
description: 변경된 코드를 합리적 동료 태세로 검토하여 구체적 탐지 시그널에 매치되는 결함 의문점을 생성합니다.
intent-class: source.review
input-authority: repository-source
not-for: [source.explain, pull-request.review]
user-invocable: true
---

# Review — 합리적 동료 의문점 생성기

중요 skill phase는 `uv run python -m scripts.skill_harness.phase_runner`로 계약을 initialize, evaluate, advance, finalize합니다.

리뷰 에이전트는 구현 에이전트를 합리적 동료로 보고, **구체적 탐지 시그널이 매치될 때만** "이 구간이 실제 문제를 일으키는가?"라는 의문을 생성한다. 스타일·취향 지적이 아니라 PR에서 더 물을 것이 남지 않게 만드는 결함 질문기다.

## 실행 모드

`/review-code`는 **단일 서브에이전트**가 14개 카테고리를 전부 순회한다.
`personas/judgment.md`는 전체 판단 태세이고 나머지 `personas/*.md` 5개 파일은
카테고리 인덱스입니다. 충돌 시 `.agents/rules/*.md`가 SSOT입니다.
구현 에이전트의 local self-review, 같은 thread 안의 수동 checklist, 또는 serial fallback은
`/review-code` 실행으로 인정하지 않는다. Runtime에서 subagent spawn
capability가 없거나 policy가 dispatch를 막으면 `/review-code`는 blocked이며,
구현 에이전트는 리뷰를 대신 수행했다고 주장하지 않고 capability gap을 보고한다.
Codex hook이 바로 위 부모를 확인했다는 근거를 주지 않으면(계약 문구로 `Codex hook에 immediate parent-bound child provenance가 없으면`)
`agent_id`만으로 바로 아래 자식(`direct-child`)을 추정하지 않습니다. 해당 runtime의
`/review-code`는 정식 근거로 사용할 수 없음(`UNAVAILABLE`)으로 blocked입니다.

`personas/judgment.md`는 전체 판단 태세이며 모든 전문 persona보다 먼저 읽습니다.
탐색 범위는 넓게 유지하되 병합 차단은 증거로 제한하고, 구현자의 반박도 reviewer의
finding과 같은 강도로 검증합니다. 나머지 5개 persona는 이 태세 아래 14개 전문
카테고리를 인덱싱합니다.
판단 decision의 executable SSOT는
`.agents/rules/constructive-skeptic-policy.json`입니다.

## 운영 모델

| 요소 | 규칙 |
|------|------|
| 전체 Persona | 잠재 결함은 폭넓게 찾고 Critical은 current-head 재현·구체적 영향·고유 root cause가 있을 때만 부여 |
| 하네스 SSOT | persona는 인덱스, `.agents/rules/*.md` 본문이 최종 판단 근거 |
| 의문점 | "이 구간이 실제 문제를 일으키는가?" 형태만 허용. 개방형 "왜?" 금지 |
| 해소 | 코드 수정 수용 또는 규칙·선례·스코프·도메인 근거로 반박 인정 |
| 미해소 | 수용/반박 인정 없음. Critical이면 루프 종료 차단 |
| Warning | 실제 운영 해 가능성이 구체적으로 관찰될 때만 생성. Info 생성 금지 |

rules/에 신규 금지·안티패턴·시그널이 추가되면 persona 인덱스가 stale해도 서브에이전트는 rules/ 본문을 직접 읽어 적용한다. persona 인덱스는 토큰 절약용이므로 같은 PR 또는 즉시 후속 PR에서 동기화한다.

## 실행 흐름

1. `git diff` (또는 `git diff --cached`)로 변경 사항을 확인한다.
2. Exact head와 실제 target agent identity를 먼저 exact session/workflow의 typed delegation에
   결속한 뒤 **그 target과 동일한 단일 리뷰 서브에이전트 1개를 디스패치**한다.

   Exact HEAD를 먼저 read tool로 읽은 뒤 한 physical line의 별도 tool call을 실행합니다:
   `python3 .agents/skills/process-ticket/scripts/delegate_state.py --workflow-id WORKFLOW_ID begin --kind review-code --target reviewer --scope EXACT_REVIEW_SCOPE --target-agent-id IMMUTABLE_RUNTIME_ACTOR_ID --reviewed-head-sha FULL_HEAD_SHA`.
   반환 JSON의 `delegation_id`는 다음 read/dispatch step에서 검증하며 shell substitution이나
   pipeline으로 같은 call에 합치지 않습니다.

   Helper는 runtime identity로 `StateHandle.attach`하고 assignment를 unique
   `delegation_id`에 저장합니다. Owner나 target을 file path 또는 display name으로 찾지
   않습니다. 디스패치 시 아래를 전달한다:

   - `personas/judgment.md`를 먼저 읽고, `personas/architecture.md`, `personas/type.md`, `personas/naming.md`, `personas/simplicity.md`, `personas/test-coverage.md`를 이어서 읽습니다. 전체 6개 파일을 판단 태세와 14 카테고리 체크리스트로 사용합니다.
   - diff 전체.
   - 이슈 맥락(목표·수용 기준·제약 사항).
   - 기반 contract 또는 domain package PR이면 관련 open ticket summary와 이미 반영된
     existing domain code context. 카테고리 4 "도메인 제네릭성 (Aggregate·Port 경계)"는
     `.agents/skills/review-code/review-heuristics.md`의 model-first DDD drift 신호를 적용하며,
     diff line만으로 통과 판정을 내리지 않는다.
   - dispatch evidence: subagent id 또는 runtime handle, 전달한 diff 기준 commit/working
     tree marker, persona 파일 목록.
   - execution trajectory evidence: 이번 owner turn의 사용자 목표, mutation·retry 요약,
     exact session/workflow snapshot, `git diff`를 각각 typed SHA-256 locator와 함께
     전달합니다. Reviewer는 코드 finding과 별도로 세 입력을 charter/process-ticket
     계약과 대조해 self-confirmation bias로 놓친 harness 위반을 감사합니다.
   - `process_state` locator는 legacy file 이름이 아니라 canonical session/workflow snapshot을
     뜻하는 submit API의 typed source key입니다. Delegate claim 직후 feature worktree CWD에서
     `python3 -m scripts.agent_harness.state_cli session inspect`를 한 physical line의 typed read로
     정확히 한 번 실행합니다. 다음 agent step에서 반환 object의 exact workflow와 delegation,
     reviewed head를 해석합니다. 해당 native tool call의 식별자, 종료 결과와 출력 원문을 보존한 뒤,
     그 출력 bytes 또는 원본 tool-result envelope의 canonical JSON SHA-256을
     `process_state:sha256:DIGEST` locator로 고정합니다. 근거의 출처는
     `authority=retained-native-tool-result`로 명시하며, 읽기 호출에 발급되지 않은 훅 receipt로
     표현하지 않습니다. Shell capture, JQ pipeline, command substitution으로 read와 해석을 합치지 않으며,
     wait 중 live workflow가 바뀌어도 조회 시 확보한 상태 기록을 다시 만들거나 digest를 바꾸지 않습니다.
     Reviewer는 이 captured readback을 submit 직전 live typed assignment identity와 대조합니다.
   - Stateful helper tool call의 native `workdir`/`cwd` metadata를 canonical owned worktree로
     지정합니다. Per-call workdir를 지원하지 않는 runtime에서는 process CWD가 이미 그 worktree일
     때만 실행하며, shell `cd`, chain, environment assignment로 CWD나 actor identity를 꾸미지 않습니다.
3. 서브에이전트는 14 카테고리를 순회하며 Critical / Warning으로 분류된 의문점
   리스트를 반환한다. 탐지 시그널에 매치되지 않은 카테고리는 "통과"로 명시한다.
   Info 섹션은 생성하지 않는다. 결과는 같은 `delegation_id`와 target identity로
   `delegate_state.py submit`에 저장한다. Critical은 `--review-finding-json`, Warning과
   수용된 반박/수정은 `--review-note-json`을 사용한다. 이 submit은 immutable `target_agent_id`와
   일치하는 실제 리뷰 runtime만 실행할 수 있으며, 구현 owner가
   target identity를 인자로 적어 대리 제출할 수 없다. 반대로 `begin`, `complete`,
   `abort`는 immutable owner actor identity와 일치하는 runtime만 실행한다.
   Local review submit은 `git_diff`, `process_state`, `execution_trajectory` 세 source의
   typed SHA-256 locator를 `--harness-audit-evidence`로 모두 제출해야 하며, 누락되면
   durable review result가 거부됩니다. 감사에서 재현 가능한 harness 위반을 발견하면
   변경 전에 확정한 해당 검사표 항목의 Critical로 제출하고 owner가 incident를 기록·교정할 때까지 pass하지
   않습니다.
4. 구현 에이전트의 응답(수정 또는 반박)을 받아 **재검증**한다. 재검증은 동일 단일 서브에이전트를 **갱신된 diff**에 대해 다시 디스패치하여 수행한다.
5. **루프 종료 조건**: 재디스패치된 서브에이전트가 **Critical을 0개 생성**하면 수렴.
   Warning은 수용, 반박, 또는 `.agents/rules/behavioral.md` Gap Triage를 통과한 후속
   work item만 허용한다 (개수 무관). Critical 미해소가 남은 상태로 루프를 종료하지
   않는다. Owner는 제출된 exact `outcome_ref`로 `delegate_state.py complete`를 실행하고,
   phase runner는 그 completion의 full `review_report`를 다시 읽어야만 완료된다.
6. **자동 수렴**: 고정 iteration 상한을 두지 않습니다. Critical이 남아 있고 승인된
   scope 안에서 구현 가능한 deterministic fix가 있으면 구현 agent가 수정하고 같은
   subagent에 재검증을 요청하는 loop를 Critical 0개까지 반복합니다. iteration 횟수는
   사용자에게 중간 승인을 요청하는 사유가 아닙니다.
7. **실제 blocker만 에스컬레이션**: 새 iteration이 직전 결정을 뒤집더라도 code,
   test, rule, issue evidence로 해소할 수 있으면 agent가 자율적으로 해소합니다. 직접적인
   spec/code 모순, 새 product/domain decision, 사용할 수 없는 credential, destructive
   external mutation처럼 `/process-ticket`의 중단 조건에 해당할 때만 사용자에게 묻습니다.
8. **평가 기준 고정**: 최초 14-category full review에서 category별 invariant와
   reproduction command를 `review_acceptance_matrix`의 항목으로 변경 전에 확정합니다. 이후
   Critical은 그 확정 항목에 매핑되고 current head에서 재현될 때만 blocking입니다.
   Reviewer가 새로운 blocking criterion을 뒤늦게 추가하거나 동일 root cause를 다른
   문장으로 반복하면 blocker를 늘리지 않고 stable finding key로 deduplicate합니다.
   Scope 또는 외부 사실이 실제로 바뀌어 검사표 확장이 필요하면 검사표를 다시 확정하고
   기존 항목까지 한 번에 전부 재검증합니다.

> **Critical만 "신규 생성 0" 강제**: Warning은 주관 재발로 수렴을 막으므로 개수 무시, Critical(동작·타입·레이어 위반)만 강제 차단. Warning 처리 경로 = 수용 / 반박 / Gap Triage 후속 work item — 수렴 판정 시 선택 경로와 근거를 iteration 로그에 명시.

> 순회 규칙: **탐지 시그널 미매치 카테고리도 "통과"로 명시.** 체크 누락과 의문점 없음을 구분.

## 심각도 정의 (의문점 weight)

| 심각도 | 성격 | 해소 요건 |
|--------|------|-----------|
| **Critical** | 아키텍처/레이어/트랜잭션 무결성/테스트 게이트/스펙 오류 | **해소 필수** — current head의 실행 가능한 재현, 현재 scope/invariant 위반, 구체적 영향, 고유 root cause가 필요. 수정 또는 근거가 명백한 반박으로 해소하며 어느 쪽도 못 하면 루프 종료 불가 |
| **Warning** | 타입 규율, YAGNI 역설, 네이밍, defensive 과다, 코드 스멜, 영속/API 규율 | **실제 운영 해 가능성이 구체적으로 관찰될 때만 보고**. 해소 또는 반박 근거 필요 — 규칙 인용·코드 선례·스코프 근거·도메인 근거 중 하나 이상 제시. 단순 "그냥 그렇게 했다"는 반박으로 인정되지 않음 |

> **Info 심각도 제거.** 가독성·스타일은 사람 리뷰어에 위임 (iteration 순환 주원인).

## 의문점 해소 프로토콜

각 의문점에 대해 구현 에이전트는 다음 중 하나를 수행한다.

### (1) 수용 (Accept)

- 코드를 수정하여 의문의 원인을 제거한다.
- 수정 요약 1줄과 함께 해소를 선언한다.
- 리뷰 에이전트는 수정된 diff가 실제로 의문을 해소했는지 재검증한다. 새 의문이 생기면 다음 iteration으로 피드한다.

### (2) 반박 (Rebut)

구현 에이전트가 코드를 유지하려면 **아래 중 하나 이상**의 근거를 제시한다.

| # | 근거 유형 | 설명 |
|---|-----------|------|
| 1 | **규칙 인용** | `.agents/rules/<file>.md`의 구체적 규칙을 인용하며, 해당 규칙이 현 상황에 적용됨을 논증 |
| 2 | **코드베이스 선례** | 같은 패턴이 코드베이스에 이미 있음을 `파일:라인`으로 증명 |
| 3 | **스코프 근거** | 현 티켓 스코프를 벗어남을 증명하고, Gap Triage decision을 남긴 뒤 `/plan-issues` 또는 `/create-ticket` 경로를 선택 |
| 4 | **도메인 근거** | 도메인 사전·스펙 문서의 해당 판단 근거를 인용 |

리뷰 에이전트는 반박을 재검증하여 **설득력 있음 → 해소**, **설득력 없음 → 미해소**로 분류한다. 단순 "그렇게 했다" / "필요 없어 보인다"는 설득력 없음으로 기각된다.

### (3) 미해소 (Unresolved)

- 수용도 반박도 없거나, 반박이 기각된 상태.
- 루프 종료 조건을 막는다. 구현 에이전트는 다른 반박을 시도하거나 수용으로 전환해야 한다.

## 의문점 카테고리 (14개)

각 카테고리의 상세(의문점 프롬프트, 탐지 시그널)는 persona 파일이 인덱싱하고, 최종 판단 근거는 `.agents/rules/*.md`가 SSOT다. 리뷰 서브에이전트는 5개 파일을 모두 로드하여 14 카테고리 전체를 순회한다.

| # | 카테고리 | 심각도 | 상세 SSOT |
|---|----------|--------|-----------|
| 1 | 아키텍처 엄수 (레이어·의존 방향) | Critical | `personas/architecture.md` |
| 2 | 타입 규율 | Warning | `personas/type.md` |
| 3 | YAGNI (You Aren't Gonna Need It) 역설 | Warning | `personas/simplicity.md` |
| 4 | 도메인 제네릭성 (Aggregate·Port 경계) | Critical | `personas/architecture.md` |
| 5 | 네이밍 엄수 | Warning | `personas/naming.md` |
| 6 | 테스트 게이트 (커버리지·신규 분기) | Critical | `personas/test-coverage.md` |
| 7 | 가독성 & 간소화 | Warning | `personas/simplicity.md` |
| 8 | API/REST 컨벤션 | Warning | `personas/test-coverage.md` |
| 9 | 영속성/Repository 규율 | Warning | `personas/architecture.md` |
| 10 | 트랜잭션 무결성 (단일 Aggregate 변경) | Critical | `personas/architecture.md` |
| 11 | 코드 스멜 / 패턴 이질성 | Warning | `personas/simplicity.md` |
| 12 | Defensive / Helper 과다 | Warning | `personas/simplicity.md` |
| 13 | Infra / 운영 일관성 | Warning | `personas/test-coverage.md` |
| 14 | 스펙 검증 / 후속 티켓 | Critical | `personas/architecture.md` |

> 카테고리 7·12는 Warning 필터링 원칙(실제 운영 해 가능성이 구체적으로 관찰될 때만 보고)을 적용하므로 스타일·가독성 수준의 지적은 생성되지 않는다.

---

사람용 `Review 결과`와 `delegate_transition_receipt`, `review_report_readback`,
`turn_harness_audit`를 작성·제출하기 전에 `references/reporting.md`를 읽습니다.
Owner도 보고서를 소비하기 전에 같은 보고 형식과 구조화된 결과 기록의 조건을 확인합니다.

## 규칙

- **모든 14개 카테고리를 단일 서브에이전트가 순회한다.** 병렬 fan-out 금지. 탐지 시그널에 매치되지 않은 카테고리도 "통과"로 보고하여 누락과 구분한다.
- **Subagent dispatch는 필수다.** 같은 구현 agent가 persona를 직접 읽고 local로
  판단한 결과는 review evidence가 아니며, `review_done: PASS`로 보고할 수 없다.
- **Turn harness audit는 기존 단일 reviewer가 함께 수행한다.** 매 turn마다 새 reviewer를
  추가하지 않고, publication 전 필수 local review가 execution trajectory, process state,
  diff를 함께 대조합니다. 세 출처의 구조화된 근거 기록이 없으면 review를 완료할 수 없습니다.
- **전체 판단 태세는 `personas/judgment.md`, 카테고리 체크리스트는 나머지 persona 파일이 인덱싱하고 rules가 최종 SSOT다.** 리뷰 서브에이전트는 6개 파일을 모두 로드한다. SKILL.md는 디스패처 역할이므로 본문 중복을 피한다.
- **규칙 본문을 복제하지 않는다.** 의문점 프롬프트가 근거로 삼는 규칙은 `rules/<file>.md`를 직접 읽어 적용한다 (SSOT).
- **체크리스트는 "구체적 시그널이 매치될 때 의문을 꺼내는 장치"지 "룰 통과 여부 체크"가 아니다.** 항목 추가/수정 시 이 성격을 유지한다.
- **Warning은 실제 운영 해 가능성이 구체적으로 관찰될 때만 보고한다.** 카테고리가 Warning이라는 이유만으로 지적을 생성하지 않는다. Info 심각도는 생성하지 않는다.
- **미해소 Critical이 남은 상태로 루프를 종료하지 않는다.** Warning은 반박 또는 Gap Triage를 통과한 후속 work item으로 해소 가능.
- **고정 review iteration 상한이나 iteration 소진을 이유로 사용자에게 중간 승인 질문을 하지 않는다.** 구현 가능한 Critical은 수정과 동일 subagent 재검증을 자동 반복한다.
- **수정은 구현 에이전트가 수행한다.** 리뷰 에이전트는 의문점 생성과 응답 재검증만 담당한다 (역할 분리).
- 수정 후 `uv run python -m scripts.agent_harness.verification_runner pre-commit` 또는 관련 root/package
  harness subset을 실행하여 회귀를 확인한다.

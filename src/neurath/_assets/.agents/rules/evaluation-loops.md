# 평가 루프

독립 평가·장기 구현·cold-read·harness evolution은 같은 adaptive contract로 current goal을
판정하고 pass 즉시 종료합니다. 상세 결정은 `.neurath/project.json (documents 슬롯)`가 소유합니다.

## 공통 contract

`Clarify → Execute → Evaluate → Reflect`는 gap authority, 미달 criterion, evidence/coverage와
접근 변경을 판정합니다. Required run은 init·phase·completion에서 current authority를 read-back합니다.

## 명확성과 질문

Ambiguity score는 우선순위일 뿐 착수·완료 권한이 아닙니다. 모든 requirement의 authority/
dependency/materiality/evidence를 보고 첫 frontier에서 repository research → reversible assumption →
user question 순으로 하나를 고릅니다. User-owned gap만 `맥락/영향/권고/근거/질문`으로 묻고,
USER 또는 repository 근거가 진행 불가를 확정한 gap만 `blocked`입니다. Evidence 없는 반복과
완전한 요청의 강제 질문은 금지합니다.

## Goal과 evidence

`GoalContract`는 goal, intent/source revision, non-empty requirements와 acceptance를 fingerprint로
고정하며 변경은 과거 authority를 stale로 만듭니다. Test, independent semantics, source readback,
user acceptance는 서로 대체할 수 없습니다.

Completion은 execution, exact coverage, evidence, alignment/drift/uncertainty/reward-hacking,
user acceptance, freshness veto의 논리곱입니다. Score는 failure를 보상하지 못하며 latest FAIL은
같은 revision의 PASS가 있어도 veto입니다.

같은 context의 test/implementation/self-score는 독립 evidence가 아닙니다. Evaluator는 finding을,
심판은 변경 전에 확정한 통과·거부 기준의 `accept|reject|defer`를 소유합니다. Host가 바로 위
부모를 확인하지 못하면(`exact parent lineage`) 바로 아래 자식의 평가 근거(`direct-child evidence`)는
정식 사용 불가(`UNAVAILABLE`)이며 root fallback 없이 semantic completion을 막습니다.
평가자 보고서가 아직 없다는 이유만으로 작업을 종료하지 않습니다. 현재 단계는 다시 이어갈 수
있게 유지합니다. `blocked`는 현재 외부 근거가 확정한 진행 불가 조건 또는 evaluate-harness
watchdog, `failed`는 형식화된 실행 실패(`ExecutionStatus.FAILED`)일 때만 허용합니다.

## Wonder/Reflect

Pass criterion은 explicit regression 없이 다시 열지 않고, 미달만 실행하되 전체 coverage는 매회 확인합니다.

- 같은 `introduced-*` root recurrence, A/B/A/B, plateau, zero progress는 `change-approach`입니다.
- 같은 `preexisting-*` family recurrence는 표본 patch가 아니라 전수 invariant 검사입니다.
- USER/repository authority가 unresolved blocker로 확정하면 우회·재질문 없이 `blocked`입니다.
- 현재 goal 판정을 깨는 재현 가능한 harness gap은 통과·거부 검사표를 다시 확정해
  회귀 검사로 승격하고, 무관한
  finding만 defer합니다. 이미 달성한 goal을 follow-up으로 다시 열지 않습니다.
- 첫 generation에 모든 authority가 pass면 즉시 `complete`입니다.

Source inventory와 다음 회차를 준비할 때
`.agents/skills/evaluate-harness/references/convergence.md`의 공통·evaluate-harness 수렴 계약을 읽습니다.

Same-goal state는 append-only이고 material recovery만 epoch을 늘리며 cross-epoch same-root는 veto입니다.

## TDD와 독립 oracle

Behavior는 Red → Green → Refactor지만 TDD는 requirement oracle이 아닙니다. 위험에 따라
allow/deny, property/metamorphic, integration, mutation, cold-read, source/user evidence를 조합합니다.
Outcome은 goal을, trajectory는 material authority를 판정하며 유효 경로 하나를 강제하지 않습니다.

변경 전에 확정한 검사표는 회귀 검사이지 의미적 완료 판정자가 아닙니다. Candidate/report는 bounded trajectory의
digest와 verdict/blocker를 결속합니다. 결정론적·모의 검사표는 실제 확률적 동작의 증거가
아니며 provider/model provenance와 multi-trial suite는 scope 승인 전 `UNAVAILABLE`입니다.

## Persistence, material action, 효율

Official typed store는 validation → authority → CAS → readback 순서입니다. USER는 current prompt/
report, executable은 exact replay만 authority입니다. Phase/Stop/finalization은 같은 revision을
재확인하며 `AWAIT_USER`는 USER acceptance만 남은 non-final scope입니다.

Read-only는 state-free입니다. Mutation은 actor-turn의 intent → 해당 호출의 실행 결과 → derived delta →
resolution으로 닫고 raw command/output/CoT와 untyped external effect를 저장하지 않습니다.

낭비는 같은 goal의 verified attainment/resource delta로 판정합니다. Progress 0 또는 regression은
저비용이어도 실패이고 positive delta는 비용만으로 실패가 아닙니다. Material duration과 goal readback은
도구 호출·소요 시간·검토의 전체 실행 기록이 아니므로 그 총계와 token은 `UNAVAILABLE`입니다. Verified dimension만
same basis·mask에서 어느 한쪽도 더 나쁘지 않은지 비교합니다(`Pareto`). 구조 검사표는 실제
runtime에서 나온 증거인지 보장하지 않습니다.

## Finding ledger

Workflow ledger는 finding evidence이지 completion이 아닙니다. CLI는 runtime-owned state만 선택합니다.

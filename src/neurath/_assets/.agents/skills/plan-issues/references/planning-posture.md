# Planning Posture

이 resource는 `/plan-issues`가 늦게 읽는 planning-specific charter입니다. 일반
implementation·review·operation에는 주입하지 않습니다.

## 질문과 자율 판단

Planning은 의심 많고 명시적이어야 합니다. Grilling mode는
한 번에 하나의 decision-shaping question만 묻고, 답변 뒤 남은 decision tree를 다시 평가합니다.

질문은 product direction, domain boundary, 권한·privacy·safety, 되돌리기 어려운
architecture trade-off처럼 사용자 판단이 필요한 높은 granularity decision에
한정합니다. 확정 결정과 DD에서 높은 confidence로 따라오는 lifecycle state,
기본 deny/allow, role boundary, 단순 CRUD policy 같은 낮은 granularity 세부사항은
agent가 근거와 함께 자율 판단하고 ledger에 저장합니다.

질문 후보가 승인된 domain boundary, permission hierarchy, privacy default, role
responsibility에서 자연스럽게 따라오면 묻지 않습니다. 답에 따라 product experience,
trust model, data ownership, safety posture, milestone 또는 work-item 경계가 달라질
때만 질문합니다. Repository·source authority인 빈칸은 먼저 조사하고, 사용자에게는
current 결과를 바꾸는 가장 upstream gap 하나만 묻습니다.

## 제품 모양과 durable planning

product vision을 기본적으로 얇은 launch slice로 압축하지 않습니다. 의도된 usable
product shape를 먼저 보존한 뒤 구현 phase로 나누며, 작은 launch slice 때문에 필요한
capability를 제거하지 않습니다.

대화가 길어져 compaction·thread reset·handoff로 결정이 사라질 수 있으면 다음 질문
전에 `.neurath/project.json (documents 슬롯)`를 갱신합니다. 확정 product decision은 chat에만
두지 않습니다. Ledger에는 확정·보류·기각 해석을 남기고 phase 4에서 durable
decision을 적절한 context, glossary, plan, ADR 문서로 승격합니다.

Planning artifact는 다음을 보존해야 합니다.

- user와 operations 언어의 product intent
- Domain Dictionary lookup 결과와 Domain Dictionary delta
- assumption
- scenario
- requirement
- non-goal
- success criteria
- glossary change
- ADR candidate

Ticket과 spec은 clean-slate agent가 chat history 없이 읽어도 오해하지 않아야 합니다.
GitHub Issue와 repository docs에는 구현 agent가 필요한 context, source file, decision,
non-goal, acceptance, verification을 명시합니다. 반대로 낡은 세부사항, 중복 서술,
확정되지 않은 추측을 쌓아 context rot을 만들지 않습니다.

작업 유형은 대상 프로젝트 지침을 따릅니다. 구현 작업은 승인된 요구사항과 검증 기준,
조사 작업은 질문·근거·산출물·종료 기준을 명시합니다. 구현 중 제품 결정을 추측하지 않습니다.

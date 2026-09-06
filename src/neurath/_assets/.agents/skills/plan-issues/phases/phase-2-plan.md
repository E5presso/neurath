# Phase 2: grilling과 계획

`grill-with-docs` posture로 판단 branch를 닫습니다.

## 절차

1. 질문하기 전에 `decision_tree`와 current clarification gap을 구성합니다.
2. 질문 후보마다 granularity gate를 적용합니다.
   - 묻기: 답에 따라 제품 경험, trust model, permission/privacy/safety boundary,
     data ownership, architecture trade-off, milestone/work item 경계가 달라지는
     decision.
   - 자율 판단: 이미 닫힌 domain boundary, 권한 hierarchy, privacy default,
     role responsibility에서 높은 confidence로 따라오는 lifecycle 상태,
     reviewer/approver, 기본 deny/allow, 단순 CRUD policy, enum name.
3. Repository/source authority인 gap은 먼저 조사하고 evidence reference로 닫습니다.
4. 남은 user-owned gap을 dependency rank와 materiality로 정렬합니다. 한 번에 가장 upstream
   결정 형성 질문 하나만 묻습니다. 질문은 agent가 자율 추론으로 닫으면 위험한 높은
   granularity decision에 한정합니다.
5. 문서나 코드가 뒷받침하면 추천 답변을 함께 제시합니다.
6. 사용자가 출시 slice를 명시적으로 요청하지 않는 한 MVP식 축소를
   제안하지 않습니다. 개인 사용, dogfooding, research, 완전한 private
   workflow 요구를 first-class product requirement로 보존합니다.
7. 사용자 답변을 해석한 뒤, user authority evidence로 exact gap을 닫습니다. 이미 닫힌 결정, DD, context 문서에서 높은
   confidence로 파생할 수 있는 세부사항을 계산합니다.
8. Evidence revision이 늘지 않았거나 같은 gap을 다시 묻는다면 progress로 세지 않고 질문을
   재작성하기 전에 근본 원인과 접근 변경 여부를 판정합니다.
9. 구체적 답변과 자율 파생 결정을 `decision_tree`에 기록합니다.
10. 확정 결정, 보류 결정, 기각된 해석, 자율 파생 결정의 근거와 confidence
   boundary를 `decision_log`에 기록합니다.
11. 다음 질문으로 넘어가기 전에 필요한 repository 저장을 완료합니다. 저장
   대상은 최소한 `decision_log`이며, compaction 뒤에도 필요한 결정은
   `.neurath/project.json (documents 슬롯)`, 새 DD 용어는 `.neurath/project.json (documents 슬롯)`, 큰
   trade-off는 ADR 후보나 spec artifact에 보존합니다.
12. 답변마다 ambiguity와 활성 child decision을 다시 계산합니다. 낮은 aggregate ambiguity는
    남은 material blocker를 상쇄하지 않습니다.
13. `language_ledger`, `domain_dictionary_delta`, `product_context`, `doc_updates`,
   `adr_candidates`를 갱신합니다.
14. resume 파일이 달라질 때마다 `compaction_resume_source`를 갱신합니다.

## 질문 형식

```text
질문 {Q-ID}: {막힌 결정 하나}
왜 중요한가: {하위 결정에 미치는 영향}
추천 답변: {근거가 있는 기본값}
대안: {비용이나 위험이 있는 1-2개 선택지}
```

## 맥락 window guard

대화가 길어지거나 사용자가 context-window warning을 보고하면 다음 결정
질문으로 넘어가기 전에 `.neurath/project.json (documents 슬롯)`를 갱신합니다.
확정 결정이 chat history나 compressed summary에만 존재하게 두지 않습니다.

## 통과 조건

`later`, `flexible`, `as needed`처럼 모호한 표현으로 branch를 닫지
않습니다.

높은 confidence로 파생 가능한 낮은 granularity 세부사항을 반복 질문으로
사용자에게 넘기지 않습니다. 반대로 근거가 부족하거나 제품 의미가 바뀌는
branch를 agent 추론으로 몰래 닫지 않습니다.

질문 후보가 granularity gate를 통과하지 못하면 질문하지 말고 자율 파생 결정으로
저장합니다.

자율 파생 결정을 repository ledger/DD/spec artifact에 저장하지 않은 상태로
다음 질문을 하지 않습니다.

확정 결정이 chat history에만 존재하면 진행하지 않습니다. rolling decision
log에 보존하거나 phase를 blocked로 종료합니다.

## 완료 evidence

- `decision_tree`
- `decision_log`
- `compaction_resume_source`
- `language_ledger`
- `domain_dictionary_delta`
- `doc_update_plan`

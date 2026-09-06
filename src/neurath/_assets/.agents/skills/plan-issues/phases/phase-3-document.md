# Phase 4: 문서 보존

승인된 스펙을 repository 문서로 보존합니다.

## 절차

1. 승인된 스펙을 `docs/plans/` 아래에 작성합니다.
2. 확정, 보류, 기각 결정을 `.neurath/project.json (documents 슬롯)`에 기록합니다.
3. 제품 context가 바뀌었으면 `docs/context/`를 갱신합니다.
4. 확정된 canonical term은 `.neurath/project.json (documents 슬롯)`에 기록합니다.
5. 되돌리기 어렵고, 맥락 없이 의외이며, 실제 trade-off가 있는 결정만
   ADR draft로 만듭니다.
6. 기각한 ADR 후보는 이유를 기록합니다.

## 통과 조건

문서 delta가 남아 있으면 GitHub Issue를 만들지 않습니다. 확정 결정이 chat
history에만 남아 있는 상태도 unresolved documentation delta입니다.

## 완료 evidence

- `persisted_spec`
- `product_context`
- `decision_log`
- `domain_dictionary_delta`
- `doc_updates`
- `adr_decisions`

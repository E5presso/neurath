# Phase 5: Sync Docs

가능한 구현 work가 모두 terminal 상태가 된 뒤 documentation을 동기화합니다.

## 절차

1. 구현이 durable behavior 또는 architecture를 바꿨으면 `/sync-docs all`을
   실행합니다.
2. Neurath 제품 의미가 unresolved이면 user-facing docs는 blocked 상태로 둡니다.
3. docs 변경이 merged 또는 approved behavior를 근거로 하는지 확인합니다.
4. phase runner state에 `sync_docs_result`를 기록합니다.

## 통과 조건

제품 의미가 unresolved라서 docs를 갱신할 수 없으면 behavior를 꾸며내지 말고
blocker를 명확히 보고합니다.

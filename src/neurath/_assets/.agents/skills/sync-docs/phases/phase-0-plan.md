# Phase 0: 문서화 범위 계획

documentation sync scope를 결정합니다.

## 절차

1. scope를 `dev`, `user`, `all`, specific component 중 하나로 parse합니다.
2. approved plan, changed code, test, manifest, existing docs를 읽습니다.
3. `/sync-dev-docs`, `/sync-user-docs`, 둘 다 중 무엇이 필요한지 결정합니다.
4. Neurath product purpose가 settled되지 않아 blocked 상태로 남아야 하는 docs를
   식별합니다.
5. source evidence와 target file이 있는 sync plan을 만듭니다.

## 통과 조건

승인되지 않은 product behavior를 실제처럼 문서화하지 않습니다.

# Phase 2: Deployed Surface Evidence

실제 client와 deployed surface를 통해 사용자-visible behavior를 검증합니다.

## 절차

1. web은 `tool:browser`, mobile은 `tool:native_mobile`로 실제 사용자 조작을 수행합니다.
2. native browser control을 standalone Playwright로 대체하지 않습니다. DOM handler 직접
   호출, JS state mutation, API-only shortcut으로 UI 검증을 대체하지 않으며 native
   control availability는 Phase 1에서 이미 확인되어 있어야 합니다.
3. client evidence에는 screenshot, video, accessibility snapshot, browser/mobile
   automation artifact 중 하나 이상을 남깁니다.
4. network/API evidence에는 request/response, HAR, status trace, API artifact 중
   하나 이상을 남깁니다.
5. persistence evidence에는 database query, row/document read-back, persistence
   artifact 중 하나 이상을 남깁니다.

## 완료 evidence

- `client_surface_evidence`
- `network_or_api_evidence`
- `persistence_evidence`

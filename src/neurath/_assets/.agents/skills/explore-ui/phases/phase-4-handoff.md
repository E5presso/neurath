# Phase 4: 구현 handoff

선택된 방향을 구현 가능한 pointer로 보존합니다.

- provider, file URL/key, exact tablet/mobile node, revision, surface, state와 sample data를 기록합니다.
- 미정 영역과 canvas-only proposal token/component를 분리합니다.
- Runtime-owned visual이 있으면 source 또는 capture link를 연결합니다.
- Repository를 수정하지 않고 `/sync-design` 또는 `/implement-ui`가 소비할
  `handoff_record`만 만듭니다.

Phase evidence는 `handoff_record`입니다. Exact node가 없으면 `direction-selected`로 종료하지 않습니다.

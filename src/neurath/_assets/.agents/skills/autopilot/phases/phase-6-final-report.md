# Phase 6: 최종 보고

terminal run report를 출력합니다.

## 필수 섹션

- target
- merged PR
- `mergeable-clean` PR
- failed 또는 blocked item과 reason
- spawned follow-up issue
- audit result
- docs sync result
- residual risk

## Terminal state

`.agents/skills/contracts.json`에 있는 terminal state만 사용합니다.

GitHub이 PR merge를 확인하지 않았으면 issue를 `merged`로 보고하지 않습니다.

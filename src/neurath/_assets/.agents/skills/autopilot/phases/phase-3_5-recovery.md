# Phase 3.5: Recovery

spawned 또는 missed follow-up issue에 대해 fixed-point recovery pass를 수행합니다.

## 절차

1. 모든 worker report를 issue set과 비교합니다.
2. 생성됐지만 spawn되지 않은 follow-up issue를 찾습니다.
3. 모든 follow-up issue가 같은 milestone 또는 parent scope에 속하는지 검증합니다.
4. 검증된 blocker를 DAG에 추가합니다.
5. 새 blocking issue가 없어질 때까지 phase 2 또는 phase 3으로 돌아갑니다.

## 통과 조건

blocking follow-up issue가 note에 언급되기만 한 상태로 run을 끝내지 않습니다.
spawn하거나, reason과 함께 skipped 처리하거나, blocked로 보고해야 합니다.

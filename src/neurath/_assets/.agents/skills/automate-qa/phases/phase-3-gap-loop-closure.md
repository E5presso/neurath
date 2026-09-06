# Phase 3: Gap And Loop Closure

관찰된 gap을 분류하고 승인된 closure loop를 수행합니다.

## 절차

1. gap을 product spec, frontend, local surface, backend/API, database/migration,
   deployment/infrastructure로 분류합니다.
2. `.agents/rules/behavioral.md`의 진단 규율에 따라 `root_cause_disposition`을 남깁니다.
   값은 `no_gap`, `routed`, `confirmed_shared_invariant`, 근거를 첨부한
   `confirmed_local_with_evidence` 중 하나입니다. 증상별 local patch를 원인 분석으로
   대체하지 않습니다.
3. `.agents/rules/behavioral.md`의 Gap Triage를 적용합니다.
4. 현재 scenario acceptance, merge safety, release safety를 깨는 gap은 현재 loop에서
   수정하거나 `/process-ticket`로 즉시 연결합니다.
5. 스펙이 불명확하면 새 구현 ticket을 만들지 말고 `/plan-issues`로 되돌립니다.
6. fix 뒤 정적·단위 검증을 먼저 끝내고 `post_fix_pre_runtime_verification`을 남깁니다.
   fix가 없거나 이관했다면 `not_applicable_no_fix` 또는 `routed`를 기록합니다.
7. deployment evidence를 확인한 뒤 native client의 fresh session 또는 cache-bypass
   regression artifact를 마지막으로 남깁니다.

## 완료 evidence

- `gap_classification`
- `root_cause_disposition`
- `triage_decision`
- `post_fix_pre_runtime_verification`
- `deployment_evidence`
- `regression_evidence`
- `loop_closure_result`

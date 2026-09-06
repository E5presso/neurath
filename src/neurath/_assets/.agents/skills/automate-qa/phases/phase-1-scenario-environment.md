# Phase 1: Scenario And Environment

승인된 scenario와 target environment를 확정합니다.

## 절차

1. `.agents/rules/e2e-tests.md`를 읽습니다.
2. scenario source가 `/plan-issues`, accepted issue, deployed regression report,
   approved product spec 중 하나인지 확인합니다.
3. 공개된 표준, browser/platform capability, library 제약은 client를 열기 전에
   `tool:source_research`로 최신 공식 문서와 primary source를 조사합니다. target
   environment에서만 판정할 수 있는 outcome과 구분합니다. 공개 capability 질문이
   없으면 `no_public_capability_question` disposition을 남깁니다.
4. 변경이 포함된 workflow라면 source 수정과 정적·단위 검증이 끝났는지 확인합니다.
   source 변경이 없으면 `no_source_change` disposition을 남깁니다. runtime client
   검증으로 구현 전 탐색이나 시각적 수치 조정을 대신하지 않습니다.
5. target environment의 web, local surface, backend, database, infrastructure
   endpoint를 식별합니다.
6. web은 `tool:browser`, mobile은 `tool:native_mobile` availability를 확인합니다. 대상
   client의 native control이 없으면 이 phase를 blocked로 종료합니다.
7. 로그인, seed data, required credentials, destructive risk를 확인합니다.

## 완료 evidence

- `scenario_source`
- `target_environment`
- `source_research_evidence`
- `pre_runtime_verification`
- `native_client_availability`

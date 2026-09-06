---
name: automate-qa
description: 의도한 behavior를 실제 web, mobile, backend, persistence outcome과 비교하는 deployed-surface QA loop를 실행합니다.
intent-class: product-surface.qa
input-authority: product-surface
not-for: [coverage.improve, source.explain]
argument-hint: "<environment URL or scenario artifact>"
user-invocable: true
---

# Automate QA

승인된 scenario가 존재한 뒤 end-to-end QA에 사용합니다. placeholder e2e generator가
아닙니다.

중요 skill phase는 `uv run python -m scripts.skill_harness.phase_runner`로
계약을 initialize, evaluate, advance, finalize합니다.

`.agents/rules/tool-runtime-map.md`를 사용합니다.

## Phase 개요

각 phase에 진입할 때 해당 phase 파일을 읽습니다.

| Phase | 목적 | 파일 |
|-------|------|------|
| 1 | scenario와 environment 확정 | `phases/phase-1-scenario-environment.md` |
| 2 | 실제 deployed surface evidence 수집 | `phases/phase-2-deployed-surface-evidence.md` |
| 3 | gap triage와 loop closure | `phases/phase-3-gap-loop-closure.md` |

1. `.agents/rules/e2e-tests.md`와 참조 scenario를 읽습니다.
2. target environment에 필요한 web, mobile, backend, database, infrastructure
   surface가 있는지 확인합니다.
3. browser 표준, platform capability, library 제약처럼 공개 자료로 판정할 수 있는
   질문은 `tool:source_research`로 최신 공식 문서와 primary source 조사를 먼저 수행합니다.
   알려진 사실을 client 실측으로 다시 발견하거나 시각적 수치를 눈대중으로 조정하지 않습니다.
4. 변경이 포함된 workflow에서는 코드 수정과 정적·단위 검증을 먼저 끝냅니다. 실제 client
   runtime 검증은 모든 구현과 비-runtime 검증이 끝난 뒤에만 시작합니다.
5. 실제 client를 통해 user-visible behavior를 실행합니다. web client는 `tool:browser`의
   runtime-native control을 사용하고, mobile client는 `tool:native_mobile`을 사용합니다.
   standalone Playwright runner를 native client 조작 대신 실행하지 않습니다.
6. UI automation은 실제 사용자 조작 경로를 사용합니다. DOM handler를 직접 호출하거나
   JS로 state를 우회 변경하지 않습니다.
7. screenshot, accessibility snapshot, request/response, server log, database
   read-back 중 scenario에 필요한 evidence를 run report에 저장합니다.
8. scenario가 persistence를 요구하면 backend API effect와 durable database state를
   검증합니다.
9. gap을 다음으로 분류합니다.
   - product spec mismatch
   - frontend behavior gap
   - mobile behavior gap
   - backend/API gap
   - database 또는 migration gap
   - deployment/infrastructure gap
10. confirmed gap은 대증적 component patch보다 공유 계약 또는 불변식의 최초 위반을
    먼저 찾은 뒤 `.agents/rules/behavioral.md`의 Gap Triage에 따라 분류합니다.
   - 현재 scenario acceptance, merge safety, release safety를 깨면 현재 loop에서
     수정하거나 `/process-ticket`으로 즉시 연결합니다.
   - 스펙이 불명확하면 새 구현 ticket을 만들지 말고 `/plan-issues`로 되돌립니다.
   - 현재 scope 밖의 독립 work item이고 지금 처리하면 WIP를 망가뜨릴 때만
     `/create-ticket`을 사용합니다.
   - 가치가 낮거나 중복이면 ticket을 만들지 않고 닫습니다.
11. `/create-ticket`을 사용한다면 reproduction step, expected behavior, observed
   behavior, evidence, label, assignee policy, milestone, dependency metadata와
   triage decision을 포함합니다. 기존 issue metadata update만 필요하면
   `/update-project-status`를 사용합니다.
12. loop closure가 요청되면 승인된 gap을 `/process-ticket`으로 보냅니다.
13. fix가 merge/deploy를 포함하면 target environment 배포 상태를 확인하고,
    cache-bypass 재접속 또는 fresh client session으로 regression을 다시 수행합니다.

scenario가 `/plan-issues`로 승인되지 않았으면 중단하고 planning step을 먼저
요청합니다.

## 필수 evidence

- `scenario_source`
- `target_environment`
- `source_research_evidence`
- `pre_runtime_verification`
- `native_client_availability`
- `client_surface_evidence`
- `network_or_api_evidence`
- `persistence_evidence`
- `gap_classification`
- `root_cause_disposition`
- `triage_decision`
- `post_fix_pre_runtime_verification`
- `deployment_evidence`
- `regression_evidence`
- `loop_closure_result`

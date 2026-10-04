---
name: automate-qa
description: 의도한 behavior를 실제 web, mobile, backend, persistence outcome과 비교하는 deployed-surface QA loop를 실행합니다.
intent-class: product-surface.qa
input-authority: product-surface
not-for: [coverage.improve, source.explain]
argument-hint: "<environment URL or scenario artifact>"
user-invocable: true
---

# qa

사용자 의도와 승인된 시나리오를 실제 배포 surface·network/API·persistence 결과에 대조한다. 정적 검사와 실제 runtime 검증을 구분한다. 필요한 client/tooling이 없으면 실제 capability gap을 기록한다. Root cause를 좁히고 승인된 fix 뒤 적절한 사전 검사·배포·회귀를 수행한다. Screenshot만으로 저장 성공이나 backend 결과를 증명하지 않는다.

## 실행

현재 사용자 지시와 `.neurath/policy.md`, `.neurath/project.json`을 따른다. 기존 Task/Assignment를 먼저 읽고, 이 스킬을 실행할 때 같은 Task에 `skill_start`한다. `phase_read`가 반환하는 다음 단계와 조건을 따르며 모든 단계 뒤에만 사용자 Task 인수를 판단한다. 별도 workflow/adaptive 원장을 만들거나 phase를 skip하지 않는다. 실패·대기는 실제 상태로 보존한다.

| 단계 ID | 완료할 결과 |
| --- | --- |
| scenario_and_environment | scenario_source, target_environment, source_research_evidence, pre_runtime_verification, native_client_availability |
| deployed_surface_evidence | client_surface_evidence, network_or_api_evidence, persistence_evidence |
| gap_and_loop_closure | gap_classification, root_cause_disposition, triage_decision, post_fix_pre_runtime_verification, deployment_evidence, regression_evidence, loop_closure_result |

원문·실제 tool 결과·agent report를 구분하고 필요한 근거를 `phase_complete`로 연결한다. Task의 인수 조건도 충족해야 `task_complete`할 수 있다.

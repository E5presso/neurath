---
name: evaluate-harness
description: Neurath harness에 failure scenario를 simulation하고 선언됐지만 강제되지 않는 rule을 찾습니다.
intent-class: harness.evaluate
input-authority: repository-source
not-for: [harness-prompt.optimize, source.explain]
argument-hint: "[scenario or 'recent session']"
user-invocable: true
---

# test-harness

구체적 failure scenario와 source capability를 정한다. 선언된 지침과 실제 강제를 구분하고 정상·실패·복구 경로를 실행 가능한 시나리오로 검사한다. 독립 evaluator에게 필요한 원문과 범위만 준다. 동일 원인은 중복하지 않고 실제 재현·영향·검증 결과를 남긴다. Fixture·패키지·설치·실제 host 검증을 섞어 완료로 보고하지 않는다.

## 실행

현재 사용자 지시와 `.neurath/policy.md`, `.neurath/project.json`을 따른다. 기존 Task/Assignment를 먼저 읽고, 이 스킬을 실행할 때 같은 Task에 `skill_start`한다. `phase_read`가 반환하는 다음 단계와 조건을 따르며 모든 단계 뒤에만 사용자 Task 인수를 판단한다. 별도 workflow/adaptive 원장을 만들거나 phase를 skip하지 않는다. 실패·대기는 실제 상태로 보존한다.

| 단계 ID | 완료할 결과 |
| --- | --- |
| define_failure_scenario | failure_scenario, source_capability_inventory, acceptance_matrix |
| independent_evaluation | project_mapping, independent_evaluator_report, finding_reproduction, root_cause_deduplication, enforcement_classification |
| gap_and_verification | weak_or_failed_gaps, patch_recommendation, deterministic_enforcement_gate, rules_skills_guidance_only, verification_result, fixed_matrix_verification_result, harness_evolution_result |

원문·실제 tool 결과·agent report를 구분하고 필요한 근거를 `phase_complete`로 연결한다. Task의 인수 조건도 충족해야 `task_complete`할 수 있다.

---
name: optimize-harness
description: AGENTS.md와 .agents/rules·.agents/skills가 모델에 주입하는 prompt token을 capability와 deterministic enforcement를 보존한 채 줄일 때 사용합니다. 개인 memory pattern 승격, 일반 harness behavior 변경, product/domain 결정, workflow typed-state 축소에는 사용하지 않습니다.
intent-class: harness-prompt.optimize
input-authority: repository-prompt-surface
not-for: [personal-memory-pattern.promote, harness.evaluate, source.refactor]
argument-hint: "[target path]"
user-invocable: true
---

# optimize-harness

Prompt surface와 실제 token/능력 기준을 먼저 관찰한다. 중복 설명과 무관한 주입을 줄이되 기능·사용자 의도·Task/phase 강제와 실제 권한 경계를 유지한다. 단순히 enforcement를 없애서 token을 줄이지 않는다. 변경 전후의 같은 behavior 시나리오로 차이를 판별하고 필요한 독립 test-harness 검토를 수행한다.

## 실행

현재 사용자 지시와 `.neurath/policy.md`, `.neurath/project.json`을 따른다. 기존 Task/Assignment를 먼저 읽고, 이 스킬을 실행할 때 같은 Task에 `skill_start`한다. `phase_read`가 반환하는 다음 단계와 조건을 따르며 모든 단계 뒤에만 사용자 Task 인수를 판단한다. 별도 workflow/adaptive 원장을 만들거나 phase를 skip하지 않는다. 실패·대기는 실제 상태로 보존한다.

| 단계 ID | 완료할 결과 |
| --- | --- |
| inventory | prompt_surface_inventory, prompt_measurement_baseline, source_capability_inventory, project_mapping, conditional_load_projection |
| optimize | prompt_delta, behavior_equivalence_check, deterministic_enforcement_gate, rules_skills_guidance_only, authoritative_pointer_readback |
| evaluate | evaluate_harness_result, verification_result |

원문·실제 tool 결과·agent report를 구분하고 필요한 근거를 `phase_complete`로 연결한다. Task의 인수 조건도 충족해야 `task_complete`할 수 있다.

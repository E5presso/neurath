---
name: promote-memory
description: private/personal memory에서 여러 session에 걸쳐 반복 확인된 사용자 선호나 작업 pattern을 privacy-safe하게 검토하여 대상 프로젝트의 적절한 durable owner 후보를 제안하거나, 사용자가 repository 반영을 승인하면 해당 owner로 승격할 때 사용합니다. 제안-only 요청에서는 repository를 수정하지 않습니다. prompt token 최적화, 일반 harness cleanup, 제품 memory architecture 설계, workflow typed-state 보존에는 사용하지 않습니다.
intent-class: personal-memory-pattern.promote
input-authority: private-personal-memory
not-for: [harness-prompt.optimize, docs.route, knowledge-graph.project]
argument-hint: "[feedback|project|reference]"
user-invocable: true
---

# memory-to-rules

여러 작업에서 반복 확인한 선호·패턴만 적절한 durable owner 후보로 제안한다. 개인·비공개 정보와 일회성 사건을 일반 규칙으로 승격하지 않는다. proposal-only 요청에서는 저장소를 수정하지 않는다. 승인된 반영은 기존 규칙과 중복·충돌을 검토하고 실제 적용 범위와 검증 결과를 남긴다.

## 실행

현재 사용자 지시와 `.neurath/policy.md`, `.neurath/project.json`을 따른다. 기존 Task/Assignment를 먼저 읽고, 이 스킬을 실행할 때 같은 Task에 `skill_start`한다. `phase_read`가 반환하는 다음 단계와 조건을 따르며 모든 단계 뒤에만 사용자 Task 인수를 판단한다. 별도 workflow/adaptive 원장을 만들거나 phase를 skip하지 않는다. 실패·대기는 실제 상태로 보존한다.

| 단계 ID | 완료할 결과 |
| --- | --- |
| execute | privacy_safe_memory_source, recurrence_evidence, existing_repository_coverage, promotion_target, private_detail_removal_check, harness_update_plan, evaluate_harness_result |

원문·실제 tool 결과·agent report를 구분하고 필요한 근거를 `phase_complete`로 연결한다. Task의 인수 조건도 충족해야 `task_complete`할 수 있다.

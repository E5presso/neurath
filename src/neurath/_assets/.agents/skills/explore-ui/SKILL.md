---
name: explore-ui
description: 구현 전에 Neurath UI 방향을 editable canvas에서 탐색하고 사용자의 exact node 선택을 받습니다. Token 동기화·구현·runtime review에는 사용하지 않습니다.
intent-class: product-ui.art-direct
input-authority: user-product-intent
not-for: [product-ui.design-mirror-sync, product-ui.approved-design-implement, product-ui.roundtrip-review, product-surface.qa]
argument-hint: "<화면 또는 실제 사용 장면> [reference·제약]"
user-invocable: true
---

# design-ui

구현 전에 화면의 의도·source·runtime 권위와 참고 자료를 확인한다. Editable canvas에서 실제 surface/state 대안을 비교하고 사용자의 exact node 선택을 받는다. 선택 전에 code 구현으로 넘어가지 않는다. 승인된 node·수정사항·다음 구현 범위를 인계한다.

## 실행

현재 사용자 지시와 `.neurath/policy.md`, `.neurath/project.json`을 따른다. 기존 Task/Assignment를 먼저 읽고, 이 스킬을 실행할 때 같은 Task에 `skill_start`한다. `phase_read`가 반환하는 다음 단계와 조건을 따르며 모든 단계 뒤에만 사용자 Task 인수를 판단한다. 별도 workflow/adaptive 원장을 만들거나 phase를 skip하지 않는다. 실패·대기는 실제 상태로 보존한다.

| 단계 ID | 완료할 결과 |
| --- | --- |
| authority_and_references | screen_authority, reference_inventory, design_source_and_runtime_authority |
| canvas_exploration | canvas_artifact, surface_frames, reference_comparison |
| user_selection | user_decision, approved_node_or_iteration |
| implementation_handoff | handoff_record |

원문·실제 tool 결과·agent report를 구분하고 필요한 근거를 `phase_complete`로 연결한다. Task의 인수 조건도 충족해야 `task_complete`할 수 있다.

---
name: implement-ui
description: 사용자가 승인한 exact canvas node를 한 surface·state에 구현하고 검증합니다. 승인 전 탐색에는 사용하지 않습니다.
intent-class: product-ui.approved-design-implement
input-authority: user-approved-canvas-node
not-for: [product-ui.art-direct, product-ui.design-mirror-sync, product-ui.roundtrip-review]
argument-hint: "<exact canvas node URL> <상주형·모바일·웹> <state>"
user-invocable: true
---

# implement-ui

승인된 exact canvas node와 한 surface/state를 확인한다. Source mapping과 runtime 문맥에 맞춰 구현하고 실제 결과를 검증한다. 사용자의 선택이 바뀌면 원래 node의 승인을 다른 설계에 재사용하지 않는다. 승인 전 탐색에는 design-ui를 사용한다.

## 실행

현재 사용자 지시와 `.neurath/policy.md`, `.neurath/project.json`을 따른다. 기존 Task/Assignment를 먼저 읽고, 이 스킬을 실행할 때 같은 Task에 `skill_start`한다. `phase_read`가 반환하는 다음 단계와 조건을 따르며 모든 단계 뒤에만 사용자 Task 인수를 판단한다. 별도 workflow/adaptive 원장을 만들거나 phase를 skip하지 않는다. 실패·대기는 실제 상태로 보존한다.

| 단계 ID | 완료할 결과 |
| --- | --- |
| execute | approved_node, surface_and_state, design_context, implementation_delta, verification_result |

원문·실제 tool 결과·agent report를 구분하고 필요한 근거를 `phase_complete`로 연결한다. Task의 인수 조건도 충족해야 `task_complete`할 수 있다.

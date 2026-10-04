---
name: review-ui
description: 승인된 canvas node와 runtime capture를 병치하고 사용자의 최종 시각 결정을 받습니다. 일반 QA에는 사용하지 않습니다.
intent-class: product-ui.roundtrip-review
input-authority: product-surface-and-approved-node
not-for: [product-ui.art-direct, product-ui.design-mirror-sync, product-ui.approved-design-implement]
argument-hint: "<approved node URL> <runtime surface·state>"
user-invocable: true
---

# review-ui

승인된 exact node와 실제 runtime capture를 나란히 비교한다. 차이와 미확인 부분을 숨기지 않고 사용자의 최종 시각 결정을 받는다. 자동 유사도나 모델의 선호를 사용자 수락으로 대체하지 않는다.

## 실행

현재 사용자 지시와 `.neurath/policy.md`, `.neurath/project.json`을 따른다. 기존 Task/Assignment를 먼저 읽고, 이 스킬을 실행할 때 같은 Task에 `skill_start`한다. `phase_read`가 반환하는 다음 단계와 조건을 따르며 모든 단계 뒤에만 사용자 Task 인수를 판단한다. 별도 workflow/adaptive 원장을 만들거나 phase를 skip하지 않는다. 실패·대기는 실제 상태로 보존한다.

| 단계 ID | 완료할 결과 |
| --- | --- |
| capture_and_compare | approved_node, runtime_capture, side_by_side_artifact, difference_record |
| user_visual_decision | user_acceptance |

원문·실제 tool 결과·agent report를 구분하고 필요한 근거를 `phase_complete`로 연결한다. Task의 인수 조건도 충족해야 `task_complete`할 수 있다.

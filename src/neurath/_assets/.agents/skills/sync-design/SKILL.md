---
name: sync-design
description: Repository token과 component mapping을 design canvas로 한 방향 동기화하고 read-back합니다. UI 탐색·구현에는 사용하지 않습니다.
intent-class: product-ui.design-mirror-sync
input-authority: repository-source
not-for: [product-ui.art-direct, product-ui.approved-design-implement, product-ui.roundtrip-review]
argument-hint: "<design file 또는 mirror 범위>"
user-invocable: true
---

# sync-design

Repository token과 component mapping을 현재 source로 삼아 design canvas에 한 방향으로 동기화한다. 적용된 node와 mapping을 read-back한다. 동기화 요청을 새로운 UI 탐색이나 구현 승인으로 해석하지 않는다.

## 실행

현재 사용자 지시와 `.neurath/policy.md`, `.neurath/project.json`을 따른다. 기존 Task/Assignment를 먼저 읽고, 이 스킬을 실행할 때 같은 Task에 `skill_start`한다. `phase_read`가 반환하는 다음 단계와 조건을 따르며 모든 단계 뒤에만 사용자 Task 인수를 판단한다. 별도 workflow/adaptive 원장을 만들거나 phase를 skip하지 않는다. 실패·대기는 실제 상태로 보존한다.

| 단계 ID | 완료할 결과 |
| --- | --- |
| execute | repository_sources, canvas_mirror_delta, read_back |

원문·실제 tool 결과·agent report를 구분하고 필요한 근거를 `phase_complete`로 연결한다. Task의 인수 조건도 충족해야 `task_complete`할 수 있다.

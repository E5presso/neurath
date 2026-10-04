---
name: review-code
description: 변경된 코드를 합리적 동료 태세로 검토하여 구체적 탐지 시그널에 매치되는 결함 의문점을 생성합니다.
intent-class: source.review
input-authority: repository-source
not-for: [source.explain, pull-request.review]
user-invocable: true
---

# review-code

정확한 diff와 목표·인수 조건·제약을 구현에 참여하지 않은 fresh reviewer 한 명에게 준다. `personas/judgment.md`를 먼저 읽고 나머지 persona와 `review-heuristics.md`의 14개 기준을 모두 검토한다. 구현자의 결론을 정답으로 주입하지 않는다.

`assignment_prepare(role="reviewer")`를 사용하며 실행 종류는 실제 필요에 맞춰 고른다. Native Codex child는 `fork_turns="none"`이다. Source 읽기와 보고에는 writer lease나 완전한 policy snapshot이 필요 없다. 자기 검토나 구현자를 재사용한 검토로 대체하지 않는다.

Finding은 실제 코드 위치, 재현 또는 구체적 실패 경로, 영향과 고유 원인을 포함한다. 취향 차이는 결함으로 만들지 않는다. 14개 기준마다 검토 결과를 남기며, 최초 검토 기준을 유지하고 같은 원인을 이름만 바꿔 늘리지 않는다. 필요한 기준 변경은 scope/새 사실과 연결한다.

Owner는 실제 보고와 subject를 읽고 accept/reject한다. 수정하면 정해진 재작업 경로를 거쳐 같은 reviewer에게 최신 diff를 제공한다. 검증 범위가 좁은 조사 결과를 전체 최종 리뷰로 승격하지 않는다. 새로운 head에는 실제 영향 재검증이 필요하며, 이전 결과를 근거 없이 상속하지 않는다.

`review_categories`, `review_report_readback`은 독립 recipient의 실제 검토 보고를 가리킨다. Reviewer가 쓰지 않은 matrix나 native 실행을 owner가 만들어 제출하지 않는다.

## 실행

현재 사용자 지시와 `.neurath/policy.md`, `.neurath/project.json`을 따른다. 기존 Task/Assignment를 먼저 읽고, 이 스킬을 실행할 때 같은 Task에 `skill_start`한다. `phase_read`가 반환하는 다음 단계와 조건을 따르며 모든 단계 뒤에만 사용자 Task 인수를 판단한다. 별도 workflow/adaptive 원장을 만들거나 phase를 skip하지 않는다. 실패·대기는 실제 상태로 보존한다.

| 단계 ID | 완료할 결과 |
| --- | --- |
| execute | subagent_dispatch, diff_marker, persona_readback, review_categories, review_report_readback |

원문·실제 tool 결과·agent report를 구분하고 필요한 근거를 `phase_complete`로 연결한다. Task의 인수 조건도 충족해야 `task_complete`할 수 있다.

검토 기준: [판단 태세](personas/judgment.md), [아키텍처](personas/architecture.md), [타입](personas/type.md), [명명](personas/naming.md), [단순성](personas/simplicity.md), [검증](personas/test-coverage.md), [탐지 기준](review-heuristics.md).

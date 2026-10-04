---
name: triage-comments
description: PR 리뷰 코멘트를 분석하여 수용/반론을 판단하고, 결정 근거를 스레드에 남깁니다.
intent-class: pull-request-comments.triage
input-authority: github-pr-state
not-for: [source.review, pull-request.monitor]
user-invocable: true
---

# pr-feedback

실제 사람 리뷰·코멘트와 unresolved thread를 읽는다. 구체적인 결함·요구를 코드와 대조해 수용하거나 근거를 갖고 반론한다. 승인된 범위의 수정은 구현·검증·독립 재검토를 거친다. 스레드에 실제 처리 결과를 남기며 본문을 읽지 않은 채 resolve/ack하지 않는다. 새 product/scope 결정만 사용자에게 묻는다.

## 실행

현재 사용자 지시와 `.neurath/policy.md`, `.neurath/project.json`을 따른다. 기존 Task/Assignment를 먼저 읽고, 이 스킬을 실행할 때 같은 Task에 `skill_start`한다. `phase_read`가 반환하는 다음 단계와 조건을 따르며 모든 단계 뒤에만 사용자 Task 인수를 판단한다. 별도 workflow/adaptive 원장을 만들거나 phase를 skip하지 않는다. 실패·대기는 실제 상태로 보존한다.

| 단계 ID | 완료할 결과 |
| --- | --- |
| execute | comment_inventory, decision_result, reply_result |

원문·실제 tool 결과·agent report를 구분하고 필요한 근거를 `phase_complete`로 연결한다. Task의 인수 조건도 충족해야 `task_complete`할 수 있다.

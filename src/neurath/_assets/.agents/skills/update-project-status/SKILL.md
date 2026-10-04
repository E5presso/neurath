---
name: update-project-status
description: GitHub Issue 또는 project status metadata를 update합니다.
intent-class: project-status.update
input-authority: github-work-item
not-for: [ticket.create, ticket.execute]
argument-hint: "<issue-number> <status>"
user-invocable: false
---

# update-status

실제 GitHub issue/project 상태와 사용자가 요청한 전이를 읽는다. 승인된 metadata만 변경하고 결과를 read-back한다. 작업이 완료되지 않았는데 Done으로 만들지 않는다. Parent 완료는 실제 child 상태가 모두 충족됐을 때만 전파한다.

## 실행

현재 사용자 지시와 `.neurath/policy.md`, `.neurath/project.json`을 따른다. 기존 Task/Assignment를 먼저 읽고, 이 스킬을 실행할 때 같은 Task에 `skill_start`한다. `phase_read`가 반환하는 다음 단계와 조건을 따르며 모든 단계 뒤에만 사용자 Task 인수를 판단한다. 별도 workflow/adaptive 원장을 만들거나 phase를 skip하지 않는다. 실패·대기는 실제 상태로 보존한다.

| 단계 ID | 완료할 결과 |
| --- | --- |
| execute | current_status, mutation_result, readback_status |

원문·실제 tool 결과·agent report를 구분하고 필요한 근거를 `phase_complete`로 연결한다. Task의 인수 조건도 충족해야 `task_complete`할 수 있다.

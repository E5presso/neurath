---
name: monitor-pr
description: Neurath PR 상태의 실제 변화를 보존하고 idle process-ticket owner를 정확히 한 번 깨웁니다.
intent-class: pull-request.monitor
input-authority: github-pr-state
not-for: [pull-request-comments.triage, pull-request.review]
argument-hint: "<pr-number>"
user-invocable: true
---

# watch-pr

명시한 PR과 head를 실제 GitHub 상태로 관찰한다. CI·리뷰·사람 코멘트·merge state의 의미 있는 변화만 보존하고 같은 상태를 반복 통지하지 않는다. 현재 host가 관찰/재개를 지원하는 경로를 사용한다. 시작 요청, 실행 중인 모니터, 실제 이벤트 전달과 처리 완료를 구분한다. Poll 또는 wake를 실행하지 않았으면 실행했다고 기록하지 않는다. 관찰자는 PR을 임의로 병합하거나 검토자로 행세하지 않는다. `mergeable-clean`은 merge 성공이 아니다.

## 실행

현재 사용자 지시와 `.neurath/policy.md`, `.neurath/project.json`을 따른다. 기존 Task/Assignment를 먼저 읽고, 이 스킬을 실행할 때 같은 Task에 `skill_start`한다. `phase_read`가 반환하는 다음 단계와 조건을 따르며 모든 단계 뒤에만 사용자 Task 인수를 판단한다. 별도 workflow/adaptive 원장을 만들거나 phase를 skip하지 않는다. 실패·대기는 실제 상태로 보존한다.

| 단계 ID | 완료할 결과 |
| --- | --- |
| start_monitor | monitor_start |
| record_subscription | monitor_event_subscription |
| resume_event | monitor_event |
| terminal_state | terminal_state |

원문·실제 tool 결과·agent report를 구분하고 필요한 근거를 `phase_complete`로 연결한다. Task의 인수 조건도 충족해야 `task_complete`할 수 있다.

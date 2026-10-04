---
name: investigate
description: bug 또는 failing check를 fix 제안 전에 재현, 격리, 설명합니다.
intent-class: defect.investigate
input-authority: repository-source
not-for: [source.explain, source.refactor]
argument-hint: "<symptom, failing command, issue number, or log excerpt>"
user-invocable: true
---

# debug

수정 전에 관측한 증상과 재현 조건을 정한다. 가장 작은 판별 가능한 재현으로 원인을 격리하고 실제 원인과 추측을 구분한다. 승인된 scope 안에서 수정·검증으로 이어가며 실패한 시도를 사용자 목표의 취소로 바꾸지 않는다. 검사 결과·원인·다음 행동을 실제 source와 연결한다.

## 실행

현재 사용자 지시와 `.neurath/policy.md`, `.neurath/project.json`을 따른다. 기존 Task/Assignment를 먼저 읽고, 이 스킬을 실행할 때 같은 Task에 `skill_start`한다. `phase_read`가 반환하는 다음 단계와 조건을 따르며 모든 단계 뒤에만 사용자 Task 인수를 판단한다. 별도 workflow/adaptive 원장을 만들거나 phase를 skip하지 않는다. 실패·대기는 실제 상태로 보존한다.

| 단계 ID | 완료할 결과 |
| --- | --- |
| execute | symptom_source, reproduction_result, root_cause, gap_triage_decision |

원문·실제 tool 결과·agent report를 구분하고 필요한 근거를 `phase_complete`로 연결한다. Task의 인수 조건도 충족해야 `task_complete`할 수 있다.

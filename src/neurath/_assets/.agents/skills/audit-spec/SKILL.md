---
name: audit-spec
description: 구현 전에 GitHub milestone, project, issue, local plan의 모호성, 모순, policy drift를 audit합니다.
intent-class: spec.audit
input-authority: repository-spec
not-for: [spec.plan, change.impact-analyze]
argument-hint: "<milestone, project, issue list, or plan path>"
user-invocable: true
---

# review-spec

구현 전에 실제 spec/issue/project/plan 원문을 기준으로 모호성·모순·누락·정책 이탈을 검토한다. 기존 정의·코드·인수 조건과 대조하고 구체적인 질문과 수정안을 만든다. 확인되지 않은 요구를 확정하거나 감사 요청을 구현으로 바꾸지 않는다.

## 실행

현재 사용자 지시와 `.neurath/policy.md`, `.neurath/project.json`을 따른다. 기존 Task/Assignment를 먼저 읽고, 이 스킬을 실행할 때 같은 Task에 `skill_start`한다. `phase_read`가 반환하는 다음 단계와 조건을 따르며 모든 단계 뒤에만 사용자 Task 인수를 판단한다. 별도 workflow/adaptive 원장을 만들거나 phase를 skip하지 않는다. 실패·대기는 실제 상태로 보존한다.

| 단계 ID | 완료할 결과 |
| --- | --- |
| execute | spec_sources, audit_findings, correction_plan |

원문·실제 tool 결과·agent report를 구분하고 필요한 근거를 `phase_complete`로 연결한다. Task의 인수 조건도 충족해야 `task_complete`할 수 있다.

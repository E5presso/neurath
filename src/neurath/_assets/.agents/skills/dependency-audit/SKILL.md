---
name: dependency-audit
description: Neurath dependency의 security, license, freshness, workspace drift를 audit합니다.
intent-class: dependency.audit
input-authority: external-primary-source
not-for: [dependency.update, change.impact-analyze]
argument-hint: "[package path or package name]"
user-invocable: true
---

# audit-deps

실제 dependency/lockfile과 사용 경로를 조사한다. Security, license, freshness와 workspace drift를 구분하며 현재 사실은 공식 source에서 확인한다. 감사 요청만으로 dependency를 변경하지 않는다. 실제 영향과 근거를 우선순위와 함께 보고한다.

## 실행

현재 사용자 지시와 `.neurath/policy.md`, `.neurath/project.json`을 따른다. 기존 Task/Assignment를 먼저 읽고, 이 스킬을 실행할 때 같은 Task에 `skill_start`한다. `phase_read`가 반환하는 다음 단계와 조건을 따르며 모든 단계 뒤에만 사용자 Task 인수를 판단한다. 별도 workflow/adaptive 원장을 만들거나 phase를 skip하지 않는다. 실패·대기는 실제 상태로 보존한다.

| 단계 ID | 완료할 결과 |
| --- | --- |
| execute | dependency_inventory, security_result, license_result, freshness_result |

원문·실제 tool 결과·agent report를 구분하고 필요한 근거를 `phase_complete`로 연결한다. Task의 인수 조건도 충족해야 `task_complete`할 수 있다.

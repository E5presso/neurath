---
name: update-dependencies
description: Neurath dependency를 통제되고 검증된 방식으로 update합니다.
intent-class: dependency.update
input-authority: external-primary-source
not-for: [dependency.audit, source.refactor]
argument-hint: "[package or dependency]"
user-invocable: true
---

# update-deps

승인된 dependency와 버전 범위를 확인한다. 호환성·변경 원인을 읽고 package와 lockfile을 일관되게 갱신한다. 필요한 최소 검사부터 필수 project check까지 실제 실행한다. 무관한 dependency·설정·권한을 변경하지 않는다. 기존 코드와 provider 동작의 차이를 확인한다.

## 실행

현재 사용자 지시와 `.neurath/policy.md`, `.neurath/project.json`을 따른다. 기존 Task/Assignment를 먼저 읽고, 이 스킬을 실행할 때 같은 Task에 `skill_start`한다. `phase_read`가 반환하는 다음 단계와 조건을 따르며 모든 단계 뒤에만 사용자 Task 인수를 판단한다. 별도 workflow/adaptive 원장을 만들거나 phase를 skip하지 않는다. 실패·대기는 실제 상태로 보존한다.

| 단계 ID | 완료할 결과 |
| --- | --- |
| execute | dependency_scope, lock_update, verification_result |

원문·실제 tool 결과·agent report를 구분하고 필요한 근거를 `phase_complete`로 연결한다. Task의 인수 조건도 충족해야 `task_complete`할 수 있다.

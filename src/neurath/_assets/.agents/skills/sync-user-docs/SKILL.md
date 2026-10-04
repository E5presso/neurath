---
name: sync-user-docs
description: 승인된 product behavior가 존재한 뒤 user-facing documentation을 동기화합니다.
intent-class: user-docs.sync
input-authority: repository-source
not-for: [docs.route, developer-docs.sync]
argument-hint: "[component or scenario]"
user-invocable: false
---

# user-docs

승인되고 실제 동작하는 기능을 사용자 관점의 목적·요청·결과로 설명한다. 내부 설정·CLI 조작을 사용자의 기본 흐름으로 떠넘기지 않는다. 지원 범위와 실제 제약을 분명히 하며 미승인 미래 기능을 약속하지 않는다. 기존 문서 구조·언어 쌍·접근성과 링크를 검증한다.

## 실행

현재 사용자 지시와 `.neurath/policy.md`, `.neurath/project.json`을 따른다. 기존 Task/Assignment를 먼저 읽고, 이 스킬을 실행할 때 같은 Task에 `skill_start`한다. `phase_read`가 반환하는 다음 단계와 조건을 따르며 모든 단계 뒤에만 사용자 Task 인수를 판단한다. 별도 workflow/adaptive 원장을 만들거나 phase를 skip하지 않는다. 실패·대기는 실제 상태로 보존한다.

| 단계 ID | 완료할 결과 |
| --- | --- |
| execute | approved_behavior, user_doc_update, verification_result |

원문·실제 tool 결과·agent report를 구분하고 필요한 근거를 `phase_complete`로 연결한다. Task의 인수 조건도 충족해야 `task_complete`할 수 있다.

---
name: sync-dev-docs
description: developer-facing docs를 현재 대상 프로젝트 code와 harness behavior에 맞춥니다.
intent-class: developer-docs.sync
input-authority: repository-source
not-for: [docs.route, user-docs.sync]
argument-hint: "[component]"
user-invocable: false
---

# dev-docs

현재 대상 프로젝트의 실제 코드·설정·검사·운영 경계를 developer 문서와 맞춘다. 문서 지도와 기존 구조를 유지하고 명령 예제는 실제 지원되는 도구/옵션인지 확인한다. 구현되지 않은 기능이나 미검증 활성화를 완료로 쓰지 않는다. 번역 쌍과 링크 정책을 지키고 관련 변경만 동기화한다.

## 실행

현재 사용자 지시와 `.neurath/policy.md`, `.neurath/project.json`을 따른다. 기존 Task/Assignment를 먼저 읽고, 이 스킬을 실행할 때 같은 Task에 `skill_start`한다. `phase_read`가 반환하는 다음 단계와 조건을 따르며 모든 단계 뒤에만 사용자 Task 인수를 판단한다. 별도 workflow/adaptive 원장을 만들거나 phase를 skip하지 않는다. 실패·대기는 실제 상태로 보존한다.

| 단계 ID | 완료할 결과 |
| --- | --- |
| execute | source_evidence, doc_update, verification_result |

원문·실제 tool 결과·agent report를 구분하고 필요한 근거를 `phase_complete`로 연결한다. Task의 인수 조건도 충족해야 `task_complete`할 수 있다.

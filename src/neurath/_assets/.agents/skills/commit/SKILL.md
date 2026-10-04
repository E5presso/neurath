---
name: commit
description: 현재 저장소의 규칙에 따라 승인되고 검증된 변경을 커밋합니다.
intent-class: git-state.commit
input-authority: repository-git-state
not-for: [session.finish, pull-request.create]
argument-hint: "<commit message intent>"
user-invocable: true
---

# commit

실제 status/diff와 저장소 commit 규칙을 확인한다. 사용자 범위의 파일만 stage하고, staged diff를 읽은 뒤 승인된 commit을 수행한다. 기존 사용자 변경을 임의로 포함하거나 버리지 않는다. 실패하는 필수 검사를 우회하지 않는다. 실제 생성된 HEAD를 읽어 기록한다. 재시도 전에 commit이 이미 생성됐는지 확인하여 중복 commit을 피한다.

## 실행

현재 사용자 지시와 `.neurath/policy.md`, `.neurath/project.json`을 따른다. 기존 Task/Assignment를 먼저 읽고, 이 스킬을 실행할 때 같은 Task에 `skill_start`한다. `phase_read`가 반환하는 다음 단계와 조건을 따르며 모든 단계 뒤에만 사용자 Task 인수를 판단한다. 별도 workflow/adaptive 원장을 만들거나 phase를 skip하지 않는다. 실패·대기는 실제 상태로 보존한다.

| 단계 ID | 완료할 결과 |
| --- | --- |
| status_and_diff | git_status, diff_review |
| stage_scope | staged_files |
| commit | commit_sha |

원문·실제 tool 결과·agent report를 구분하고 필요한 근거를 `phase_complete`로 연결한다. Task의 인수 조건도 충족해야 `task_complete`할 수 있다.

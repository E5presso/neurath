---
name: checkpoint
description: 긴 작업 중 되돌릴 수 있는 WIP checkpoint를 만듭니다.
intent-class: git-state.checkpoint
input-authority: repository-git-state
not-for: [git-state.commit, session.finish]
argument-hint: "[short reason]"
user-invocable: true
---

# checkpoint

사용자가 요청한 범위의 되돌릴 수 있는 WIP checkpoint를 만든다. 실제 diff/status와 필요 검사를 확인하고 checkpoint가 보존하는 commit·파일·남은 요구를 명시한다. Checkpoint는 사용자 Task의 완료나 push/배포의 증명이 아니다.

## 실행

현재 사용자 지시와 `.neurath/policy.md`, `.neurath/project.json`을 따른다. 기존 Task/Assignment를 먼저 읽고, 이 스킬을 실행할 때 같은 Task에 `skill_start`한다. `phase_read`가 반환하는 다음 단계와 조건을 따르며 모든 단계 뒤에만 사용자 Task 인수를 판단한다. 별도 workflow/adaptive 원장을 만들거나 phase를 skip하지 않는다. 실패·대기는 실제 상태로 보존한다.

| 단계 ID | 완료할 결과 |
| --- | --- |
| execute | git_status, verification_result, checkpoint_result |

원문·실제 tool 결과·agent report를 구분하고 필요한 근거를 `phase_complete`로 연결한다. Task의 인수 조건도 충족해야 `task_complete`할 수 있다.

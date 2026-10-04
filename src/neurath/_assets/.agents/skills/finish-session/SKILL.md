---
name: finish-session
description: 현재 coding-agent session의 검증된 변경을 사용자의 승인 한 번으로 commit, 현재 branch push, Graphify 증분 갱신, Neurath worktree claim release까지 마무리합니다. 사용자가 “세션 마무리”, “커밋·푸시·graphify하고 release”, “작업을 끝내고 worktree를 풀어 달라”처럼 전체 종료 수순을 승인했을 때 사용합니다.
intent-class: session.finish
input-authority: runtime-typed-state
not-for: [git-state.commit, pull-request.create]
argument-hint: "<commit message intent>"
user-invocable: true
---

# finish-session

사용자가 승인한 종료 범위를 확인한다. 실제 status/diff와 필수 검사를 확인하고 선택된 변경을 commit·현재 branch push한다. 기존 승인은 범위가 같으면 반복해서 묻지 않는다. 실제 local/remote HEAD가 일치하는지 `publication_read`로 확인한다. 필요한 Graphify 갱신은 실제 실행 결과로 기록한다. 보유한 writer lease를 정확한 checkout/generation으로 반환하고 모든 사용자 요구가 충족된 때 Task를 완료한다. 체크포인트나 claim 반환만으로 요구를 완료하지 않는다.

## 실행

현재 사용자 지시와 `.neurath/policy.md`, `.neurath/project.json`을 따른다. 기존 Task/Assignment를 먼저 읽고, 이 스킬을 실행할 때 같은 Task에 `skill_start`한다. `phase_read`가 반환하는 다음 단계와 조건을 따르며 모든 단계 뒤에만 사용자 Task 인수를 판단한다. 별도 workflow/adaptive 원장을 만들거나 phase를 skip하지 않는다. 실패·대기는 실제 상태로 보존한다.

| 단계 ID | 완료할 결과 |
| --- | --- |
| status_and_diff | session_finish_approval, git_status, diff_review |
| stage_scope | staged_files |
| commit | commit_sha |
| push_readback | push_head_match |
| graphify_update | graphify_receipt |
| worktree_release | worktree_release_receipt |

원문·실제 tool 결과·agent report를 구분하고 필요한 근거를 `phase_complete`로 연결한다. Task의 인수 조건도 충족해야 `task_complete`할 수 있다.

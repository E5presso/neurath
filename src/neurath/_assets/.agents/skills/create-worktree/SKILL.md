---
name: create-worktree
description: GitHub Issue용 isolated Git worktree와 branch를 만듭니다.
intent-class: worktree.create
input-authority: github-work-item
not-for: [ticket.execute, git-state.checkpoint]
argument-hint: "<issue-number>"
user-invocable: false
---

# Create Worktree

Operational phase는 `.neurath/run engine scripts.skill_harness.phase_runner` 실행 결과를 잇습니다.
`current`는 recovery 전용이며 마지막 `complete --terminal-state`가 terminal CAS를 닫습니다.

1. 요청된 작업과 대상 저장소의 branch·worktree 규칙, 현재 Git 상태를 확인합니다.
2. Source checkout native CWD에서 현재 runtime actor로 typed worktree claim을 얻습니다.
3. 사용자 지정 base가 있으면 그것을 확인합니다. 없으면 remote HEAD 또는 저장소의 현재 기본 branch를 확인합니다. 특정 branch 이름을 가정하지 않습니다.
4. 대상 프로젝트의 규칙에 따라 새 branch와 분리된 worktree 경로를 정합니다. 규칙이 없으면 작업을 식별할 수 있는 충돌 없는 이름을 사용합니다.
5. 동일 경로·branch가 존재하면 소유권과 작업을 확인하고, 다른 작업의 자산을 재사용하거나 삭제하지 않습니다.
6. `git worktree add -b <branch> <path> <base>`를 실제 확인한 값으로 실행합니다.
7. 새 worktree native CWD에서 같은 actor로 typed claim을 얻고 Git identity·branch·path를 다시 확인합니다.
8. process-ticket에서는 target claim 뒤 `.neurath/run skill process-ticket assert_worktree_isolation.sh --init ISSUE_NUMBER`로 격리를 확인합니다.
9. 작업에 필요한 프로젝트별 런처·문서 바인딩과 이미 존재하는 지식 그래프의 사용 가능 여부를 확인합니다.
10. worktree의 절대 경로, branch, base, 소유권 결과를 반환합니다.

Claim 충돌과 경로 충돌을 강제로 우회하지 않습니다. 다른 worktree의 미커밋 변경을 보존합니다.

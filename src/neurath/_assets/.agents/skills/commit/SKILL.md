---
name: commit
description: 현재 저장소의 규칙에 따라 승인되고 검증된 변경을 커밋합니다.
intent-class: git-state.commit
input-authority: repository-git-state
not-for: [session.finish, pull-request.create]
argument-hint: "<commit message intent>"
user-invocable: true
---

# Commit

Operational phase는 `.neurath/run engine scripts.skill_harness.phase_runner` 실행 결과를 잇습니다.
`current`는 recovery 전용이며 마지막 `complete --terminal-state`가 terminal CAS를 닫습니다.

1. 현재 사용자의 커밋 승인 범위와 대상 저장소 지침을 확인합니다.
2. `git status --short --branch`, staged/unstaged diff와 파일 소유권을 확인합니다.
3. 관련 파일만 stage하고 대상 프로젝트가 정한 검증을 수행합니다.
4. commit 형식·scope·언어·issue 연결 규칙은 대상 저장소의 지침을 따릅니다. 규칙이 없다면 변경 목적이 드러나는 간결한 메시지를 사용합니다.
5. 기존 Git hook을 유지한 채 commit하고 새 SHA와 남은 변경을 확인합니다.

`--no-verify`로 검증을 우회하지 않습니다. Hook 실패 시 원인을 해결합니다.
커밋 승인을 push 또는 공개 배포 승인으로 확장하지 않습니다.

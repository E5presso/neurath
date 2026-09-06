---
name: update-project-status
description: GitHub Issue 또는 project status metadata를 update합니다.
intent-class: project-status.update
input-authority: github-work-item
not-for: [ticket.create, ticket.execute]
argument-hint: "<issue-number> <status>"
user-invocable: false
---

# Update Project Status

Operational phase는 `uv run python -m scripts.skill_harness.phase_runner` 실행 결과를 잇습니다.
`current`는 recovery 전용이고 마지막 `complete --terminal-state`가 terminal CAS를 닫습니다.

GitHub Issues와 GitHub Projects만 사용합니다.

1. issue와 current project field를 읽습니다.
2. requested status가 존재하는지 확인합니다.
3. GitHub connector 또는 `gh`로 status를 update합니다.
4. issue 또는 project item을 다시 읽어 mutation을 검증합니다.
5. before/after value를 보고합니다.

명시적 user approval 없이 새 project field나 status를 만들지 않습니다.

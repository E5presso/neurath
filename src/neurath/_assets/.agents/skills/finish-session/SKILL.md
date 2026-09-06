---
name: finish-session
description: 현재 coding-agent session의 검증된 변경을 사용자의 승인 한 번으로 commit, 현재 branch push, Graphify 증분 갱신, Neurath worktree claim release까지 마무리합니다. 사용자가 “세션 마무리”, “커밋·푸시·graphify하고 release”, “작업을 끝내고 worktree를 풀어 달라”처럼 전체 종료 수순을 승인했을 때 사용합니다.
intent-class: session.finish
input-authority: runtime-typed-state
not-for: [git-state.commit, pull-request.create]
argument-hint: "<commit message intent>"
user-invocable: true
---

# Finish Session

현재 coding-agent session의 작업을 원격 branch와 지식 그래프에 보존하고 다른 session이
worktree를 claim할 수 있게 반환합니다. Native client process 자체를 종료하는 skill은 아닙니다.
여기서 `release`는 `Neurath root worktree`의 typed claim 해제이며 제품 version release가 아닙니다.

## 결정적 phase 실행

Operational phase는 `uv run python -m scripts.skill_harness.phase_runner` 실행 결과를 잇습니다.
`current`는 recovery 전용이고 마지막 `complete --terminal-state`가 terminal CAS를 닫습니다.

## Tool runtime 호환성

`.agents/rules/tool-runtime-map.md`를 사용합니다. Commit은 `/commit`, 그래프 갱신은
`/graphify`의 현재 계약을 따릅니다.

## 승인 경계

사용자가 이 session finish bundle을 한 번의 명시적 사용자 승인으로 요청하면 아래 전체
순서를 승인한 것으로 봅니다. 단계별 추가 승인을 다시 묻지 않습니다. Credential 부재,
non-fast-forward, 검증 실패, Graphify 실패, typed release 실패처럼 다음 단계를 안전하게
수행할 수 없는 경우에만 중단하고 이미 끝난 단계와 외부 상태를 정확히 보고합니다.

일반 `/commit`이나 `process-ticket`의 중간 commit은 이 skill을 암시하지 않습니다.

## 실행 순서

1. `git status --short --branch` 실행으로 현재 branch와 변경 범위를 고정합니다.
2. staged와 unstaged diff 검사로 사용자 변경과 무관한 파일이 섞이지 않았는지 확인합니다.
3. 관련 파일만 stage합니다.
4. `/commit` 계약에 따라 대상 저장소의 commit 규칙에 맞게 commit하고 exact commit SHA를 읽습니다.
5. 현재 branch를 push하고 remote HEAD를 다시 읽습니다. Local HEAD와 remote HEAD가 exact하게
   같지 않으면 claim을 유지한 채 중단합니다.
6. Claim을 유지한 상태에서 `/graphify` 계약에 따라 `graphify update .` 실행을 완료하고
   `graphify-out/graph.json`과 report 갱신 결과를 읽습니다. 실패하면 claim을 release하지 않습니다.
7. 모든 선행 evidence가 유효할 때만 다음 typed CLI로 worktree claim을 release하고 구조화된 처리 결과를 다시 읽습니다.

```bash
python3 -m scripts.agent_harness.state_cli worktree release
```

처리 결과의 `released`가 `true`이고 반환된 claim이 직전에 소유한 exact worktree, session,
actor를 가리킬 때만 terminal state `finished`를 사용합니다.

`--no-verify`, force push, 제품 version workflow, tag 생성, `main` 승격은 이 skill의 범위가
아닙니다.

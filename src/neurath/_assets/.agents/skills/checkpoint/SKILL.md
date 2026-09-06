---
name: checkpoint
description: 긴 작업 중 되돌릴 수 있는 WIP checkpoint를 만듭니다.
intent-class: git-state.checkpoint
input-authority: repository-git-state
not-for: [git-state.commit, session.finish]
argument-hint: "[short reason]"
user-invocable: true
---

# Checkpoint

Operational phase는 `uv run python -m scripts.skill_harness.phase_runner` 실행 결과를 잇습니다.
`current`는 recovery 전용이고 마지막 `complete --terminal-state`가 terminal CAS를 닫습니다.

risky refactor, 큰 harness edit, 긴 autonomous run 전에 사용합니다.

1. `git status --short --branch`를 실행합니다.
2. changed file list를 검사하고 unrelated user work가 실수로 포함되지 않게 합니다.
3. 현재 순간에 충분히 저렴한 가장 좁은 관련 verification을 실행합니다.
4. 사용자가 checkpoint를 요청했거나 현재 run에 rollback point가 명시적으로
   필요할 때만 WIP commit을 만듭니다.
5. subject는 명확히 temporary로 작성합니다.

```text
chore: checkpoint <reason>
```

failing gate를 피하려고 checkpoint commit을 사용하지 않습니다. verification gap은
분명히 보고합니다.

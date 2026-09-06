---
name: update-dependencies
description: Neurath dependency를 통제되고 검증된 방식으로 update합니다.
intent-class: dependency.update
input-authority: external-primary-source
not-for: [dependency.audit, source.refactor]
argument-hint: "[package or dependency]"
user-invocable: true
---

# Update Dependencies

중요 skill phase는 `uv run python -m scripts.skill_harness.phase_runner`로 계약을 initialize, evaluate, advance, finalize합니다.

1. 사용자가 정확한 dependency를 지목하지 않았다면 먼저 `/dependency-audit`를
   실행합니다.
2. Current runtime actor와 native CWD가 확정된 뒤 typed claim을 실행합니다.

   ```bash
   python3 -m scripts.agent_harness.state_cli worktree claim
   ```

   다른 owner와 충돌하거나 runtime identity가 없으면 dependency mutation을 시작하지 않습니다.
3. 요청을 만족하는 가장 작은 dependency set만 update합니다.
4. Exact `uv.lock` observable을 material-action intent에 준비한 뒤 한 physical line의
   `uv lock`을 실행합니다.
5. lockfile change에서 unexpected major upgrade를 검사합니다.
6. `uv run python -m scripts.agent_harness.verification_runner package-check`,
   `uv run python -m scripts.agent_harness.verification_runner pre-commit`, 필요한 package-specific runtime smoke test를
   실행합니다.
7. 변경된 package, notable transitive change, residual risk를 보고합니다.

사용자가 명시적으로 platform decision을 바꾸지 않는 한 Python minimum version,
대상 프로젝트의 타입 검사·프레임워크 정책을 임의로 바꾸지 않습니다.

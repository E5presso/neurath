---
name: dependency-audit
description: Neurath dependency의 security, license, freshness, workspace drift를 audit합니다.
intent-class: dependency.audit
input-authority: external-primary-source
not-for: [dependency.update, change.impact-analyze]
argument-hint: "[package path or package name]"
user-invocable: true
---

# Dependency Audit

중요 skill phase는 `uv run python -m scripts.skill_harness.phase_runner`로 계약을 initialize, evaluate, advance, finalize합니다.

1. root `pyproject.toml`, package `pyproject.toml`, `uv.lock`을 검사합니다.
2. `uv lock --check`를 실행합니다.
3. 유용하면 target scope에 `uv tree`를 실행합니다.
4. 다음을 확인합니다.
   - dependency version drift
   - unused direct dependency
   - missing workspace source
   - dev-only package의 unexpected runtime dependency
   - Python 3.14와 incompatible package
   - 목적에 비해 과도하거나 누락된 선택 의존성
5. dependency를 바꾸면 `uv lock`,
   `uv run python -m scripts.agent_harness.verification_runner package-check`,
   `uv run python -m scripts.agent_harness.verification_runner pre-commit`을 실행합니다.

type checker를 pyrefly에서 다른 도구로 바꾸지 않습니다.

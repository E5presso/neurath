---
name: sync-dev-docs
description: developer-facing docs를 현재 대상 프로젝트 code와 harness behavior에 맞춥니다.
intent-class: developer-docs.sync
input-authority: repository-source
not-for: [docs.route, user-docs.sync]
argument-hint: "[component]"
user-invocable: false
---

# Sync Dev Docs

중요 skill phase는 `uv run python -m scripts.skill_harness.phase_runner`로 계약을 initialize, evaluate, advance, finalize합니다.

developer docs에는 `README.md`, package README, `docs/context/`,
`docs/decisions/`, `docs/plans/`, harness docs가 포함됩니다.

1. 편집 전 code, package metadata, test, deployment manifest를 검사합니다.
2. intent가 아니라 evidence에 맞춰 docs를 갱신합니다.
3. 되돌리기 어려운 technical choice는 ADR candidate로 포착합니다.
4. `/plan-issues`가 제품 목적을 확정하기 전에는 product purpose neutral하게
   유지합니다.
5. 관련 docs 또는 harness check를 실행합니다.

---
name: review-ui
description: 승인된 canvas node와 runtime capture를 병치하고 사용자의 최종 시각 결정을 받습니다. 일반 QA에는 사용하지 않습니다.
intent-class: product-ui.roundtrip-review
input-authority: product-surface-and-approved-node
not-for: [product-ui.art-direct, product-ui.design-mirror-sync, product-ui.approved-design-implement]
argument-hint: "<approved node URL> <runtime surface·state>"
user-invocable: true
---

# Review UI

`uv run python -m scripts.skill_harness.phase_runner`로 phase를 initialize, evaluate, advance,
finalize합니다.

| Phase | 목적 | 파일 |
|---|---|---|
| 1 | Runtime capture와 병치 | [phases/phase-1-capture-compare.md](phases/phase-1-capture-compare.md) |
| 2 | 사용자 시각 결정 | [phases/phase-2-user-decision.md](phases/phase-2-user-decision.md) |

`.agents/design-collaboration-policy.json`을 읽고, `.agents/rules/tool-runtime-map.md`의
`tool:design_canvas`, `tool:browser`와 필요한 경우
`tool:native_mobile`을 사용합니다.

Approved node와 runtime capture는 같은 surface, viewport, state와 sample data여야 합니다.
Runtime-owned visual은 실제 runtime capture만 비교합니다.

사용자만 최종 시각 승인을 내립니다. Agent critique, screenshot 존재, pixel metric, token parity,
accessibility와 browser green은 승인 근거가 아닙니다. 사용자가 아직 결정하지 않았으면
`review-ready`, 승인하면 `accepted`, 수정 요청이면 `revision-requested`, native tool이나 exact
comparison authority가 없으면 `blocked`, capture·canvas write가 실패하면 `failed`입니다.

Canvas artifact를 삭제해도 collaboration capability와 connector 등록은 유지합니다. 둘의
retirement는 별도 사용자 결정입니다.

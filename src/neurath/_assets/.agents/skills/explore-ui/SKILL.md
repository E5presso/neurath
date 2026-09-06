---
name: explore-ui
description: 구현 전에 Neurath UI 방향을 editable canvas에서 탐색하고 사용자의 exact node 선택을 받습니다. Token 동기화·구현·runtime review에는 사용하지 않습니다.
intent-class: product-ui.art-direct
input-authority: user-product-intent
not-for: [product-ui.design-mirror-sync, product-ui.approved-design-implement, product-ui.roundtrip-review, product-surface.qa]
argument-hint: "<화면 또는 실제 사용 장면> [reference·제약]"
user-invocable: true
---

# Explore UI

Reference와 후보를 같은 editable canvas에 두고 사용자가 직접 수정·선택하게 합니다.
선택 전에는 production component나 token을 구현하지 않습니다.

`uv run python -m scripts.skill_harness.phase_runner`로 phase를 실행하고, 진입한 phase 파일만
읽습니다.

| Phase | 목적 | 파일 |
|---|---|---|
| 1 | 제품·reference 권위 | [phases/phase-1-authority.md](phases/phase-1-authority.md) |
| 2 | Canvas 탐색 | [phases/phase-2-exploration.md](phases/phase-2-exploration.md) |
| 3 | 사용자 선택 | [phases/phase-3-user-selection.md](phases/phase-3-user-selection.md) |
| 4 | 구현 handoff | [phases/phase-4-handoff.md](phases/phase-4-handoff.md) |

`.agents/design-collaboration-policy.json`과 다음 reference를 먼저 읽습니다.

새 방향에서는 다음 reference를 읽습니다.

- [제품·화면 정본](references/product-authority.md)
- [Reference evidence](references/reference-evidence.md)
- [Canvas와 review](references/render-and-review.md)

## Native canvas만 사용

`.agents/rules/tool-runtime-map.md`의 `tool:design_canvas`와 policy가 정한 provider를 사용합니다.
Native tool이나 file authority가 없으면 `blocked`입니다.

제품 UI 방향을 `visualize`로 대체하지 않습니다. HTML mockup, raster 합성물, screenshot 위
transparent control, 자연어 mood board를 editable canvas의 대체물로 만들지 않습니다.

- Reference 원본은 `References` 영역에 보존하고 후보와 나란히 봅니다.
- 태블릿과 모바일은 별도 node이며 겹치지 않습니다.
- Runtime-owned visual은 runtime capture·static export 또는 slot만 사용합니다.
- Canvas token은 mirror 또는 proposal이며 이 skill에서 repository를 수정하지 않습니다.
- Agent 평가나 score는 사용자 선택을 대신하지 않습니다.
- Design content reset은 token·brand·기존 visual·논의·canvas artifact만 지울 수 있습니다.
  Policy, 이 skill과 나머지 collaboration skill, connector 등록과 regression oracle은
  capability이므로 함께 삭제하지 않습니다.
- Repository design source가 아직 없으면 `clean-slate`로 기록하고 임의 값을 정본으로
  만들지 않습니다.

## 종료

사용자가 exact canvas node를 선택하면 `direction-selected`, 추가 탐색이면 `needs-more-exploration`, native
canvas가 없으면 `blocked`입니다. 선택을 추론하지 않습니다.
